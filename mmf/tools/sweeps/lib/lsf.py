# Copyright (c) Facebook, Inc. and its affiliates.

# Copied from fairseq. Mostly written by @myleott. Adapted accordingly for mmf
import datetime
import itertools
import os
import random
import shlex
import shutil
import subprocess
from collections import OrderedDict
from glob import glob
import sys
from mmf.utils.general import get_mmf_root


def main(get_grid, postprocess_hyperparams, args):
    if args.local:
        args.num_nodes = 1
    args.num_gpus = int(args.gpus.split('=')[1][:1])
    # compute all possible hyperparameter configurations
    grid = get_grid(args) # model sweep gets its input
    grid_product = list(itertools.product(*[hp.values for hp in grid]))

    # randomly shuffle configurations
    random.seed(args.seed)
    random.shuffle(grid_product)

    for i, hp_values in enumerate(grid_product):
        config = OrderedDict()
        for hp, value in zip(grid, hp_values):
            config[hp.name] = hp
            config[hp.name].current_value = value

        # postprocess hyperparams
        postprocess_hyperparams(args, config)

        # launch training
        job_id = launch_train(args, config)
        if job_id is not None:
            print(f"Launched {job_id}")

        if args.sequential and not args.local and job_id is not None:
            args.dep = job_id

        if i == args.t - 1:
            break


def copy_all_python_files(source, snapshot_main_dir, code_snapshot_hash):
    """
    Copies following files from source to destination:
        a) all *.py files at direct source location.
        b) all mmf/*.py recursively.
    """
    os.makedirs(snapshot_main_dir, exist_ok=True)
    destination = os.path.join(snapshot_main_dir, code_snapshot_hash)
    assert not os.path.exists(
        destination
    ), f"Code snapshot: {code_snapshot_hash} alredy exists"
    os.makedirs(destination)
    all_pys = (
        glob(os.path.join(source, "mmf/**/*.py"), recursive=True)
        + glob(os.path.join(source, "tools/**/*.py"), recursive=True)
        + glob(os.path.join(source, "*.py"))
    )

    for filepath in all_pys:
        directory, filename = os.path.split(filepath)
        if directory:
            os.makedirs(os.path.join(destination, directory), exist_ok=True)
        shutil.copy2(
            os.path.join(source, filepath), os.path.join(destination, filepath)
        )
    return destination


def launch_train(args, config):
    def dry_run(msg):
        if args.dry_run:
            print(f"| dry-run:  {msg}")
        return args.dry_run

    destination = ""
    if args.snapshot_code:
        # Currently hash is just the current time in ISO format.
        code_snapshot_hash = datetime.datetime.now().isoformat()
        destination = copy_all_python_files(
            ".", "lsf_snapshot_code", code_snapshot_hash
        )

    # compute save_dir
    save_dir_key = ".".join(
        filter(
            lambda save_dir_key: save_dir_key is not None,
            [hp.get_save_dir_key() for hp in config.values()],
        )
    )
    save_dir_key = save_dir_key.replace(",", "_")
    num_total_gpus = args.num_nodes * args.num_gpus
    save_dir = os.path.join(
        args.checkpoints_dir, f"{args.prefix}/{save_dir_key}"
    )
    tensorboard_logdir = os.path.join(
        args.tensorboard_logdir, f"{args.prefix}/{save_dir_key}"
    )



    # construct training commands
    train_cmd = [
        "python3",
        "-u",
        os.path.join(get_mmf_root(), "..", "mmf_cli", "run.py"),
    ]


    # create save directory if it doesn"t exist
    if not os.path.exists(save_dir):
        if not dry_run(f"create directory: {save_dir}"):
            os.makedirs(save_dir)

        # copy baseline model
        checkpoint_last = os.path.join(save_dir, "baseline_model.ckpt")
        if (
            args.baseline_model
            and not os.path.exists(checkpoint_last)
            and not dry_run(f"initialize with baseline model: {args.baseline_model}")
        ):
            if not os.path.exists(args.baseline_model):
                raise FileNotFoundError(
                    f"Cannot find baseline model: {args.baseline_model}"
                )
            shutil.copyfile(args.baseline_model, checkpoint_last)

    # check for whether the run failed
    if has_finished(save_dir):
        if args.resume_finished:
            dry_run(f"restart previously finished run: {save_dir}")
        else:
            print(f"skip finished run (override with --resume-finished): {save_dir}")
            return
    elif has_failed(save_dir):
        if args.resume_failed:
            dry_run(f"resume failed run: {save_dir}")
        else:
            print(f"skip failed run (override with --resume-failed): {save_dir}")
            return

    # if run_type is test
    if args.run_type == 'test':
        assert args.resume_file is not None
        # if not then it is null
        train_cmd.extend(["checkpoint.resume_file", os.path.join(save_dir, args.resume_file)])

    # if resuming training from a checkpoint
    # this will resume from the current.ckpt
    elif args.resume == "True":
        train_cmd.extend(["checkpoint.resume", "True"])
        # if a specific file is desired to run from
        if args.resume_file is not None:
            train_cmd.extend(["checkpoint.resume_file", args.resume_file])
        # this will resume from the best.ckpt
        elif args.resume_best == "True":
            train_cmd.extend(["checkpoint.resume_best", "True"])

    # if folder is created, i.e. experiment could already be running, and run_type is not test
    elif has_started(save_dir):
        print(f"skip in progress run: {save_dir}")
        return


    #train_cmd.extend(["distributed.world_size", str(args.num_nodes * args.num_gpus)])
    #if args.num_nodes > 1:
    #    train_cmd.extend(["distributed.port", str(get_random_port())])

    #if args.config is not None:
    #    train_cmd.extend(["config", args.config])


    train_cmd.extend(["env.save_dir", save_dir])
    train_cmd.extend(["env.cache_dir", args.cache_dir])
    train_cmd.extend(["env.data_dir", args.data_dir])
    # how many models to keep based on best (eligible checkpoints)
    train_cmd.extend(["checkpoint.max_to_keep", args.max_to_keep])


    if args.tensorboard:
        train_cmd.extend(["training.tensorboard", "1"])
        train_cmd.extend(["env.tensorboard_logdir", tensorboard_logdir])
    for hp in config.values():
        train_cmd.extend(map(str, hp.get_cli_args()))
    if args.extra_args is not None and len(args.extra_args) > 0:
        # convert commands with equal sign to the other format without the equal sign
        # e.g. ["training.batch_size=128"] to ["training.batch_size", "128"]
        extra_args = [c for arg in args.extra_args for c in arg.split("=")]
        train_cmd.extend(extra_args)
    if args.dry_run:
        print(train_cmd)
        train_cmd_str = " ".join(train_cmd)
        dry_run(f"train command: {train_cmd_str}")

    # start training
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "2"
    if args.local:
        assert (
            args.num_nodes == 1
        ), "distributed training cannot be combined with --local"
        if not dry_run("start training locally"):
            if "CUDA_VISIBLE_DEVICES" not in env:
                env["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, range(args.num_nodes * args.num_gpus)))
            env["NCCL_DEBUG"] = "INFO"
            train_proc = subprocess.Popen(train_cmd, env=env)
            train_proc.wait()
    else:

        # creating log files
        train_log = os.path.join(save_dir, "train.log")
        train_stdout = os.path.join(save_dir, "output_file_%J.out")  # %j = lsf job id
        train_stderr = os.path.join(save_dir, "error_file_%J.err")  # %j = lsf job id

        # set environment
        if args.num_nodes > 1:
            env["NCCL_SOCKET_IFNAME"] = "^docker0,lo"
            env["NCCL_DEBUG"] = "INFO"
        else:
            env["NCCL_SOCKET_IFNAME"] = ""

        # command to run the model
        run_cmd = train_cmd
        run_cmd_str = " ".join(map(shlex.quote, run_cmd))

        # where we are currently building the command
        if not args.salloc:
            excluded_hosts = os.environ.get("EXCLUDED_HOSTS", None)
            included_hosts = os.environ.get("INCLUDED_HOSTS", None)

            # general bsub commands
            bsub_cmd_str = '#BSUB -J {}\n'.format(f"{args.prefix}.{save_dir_key}")
            bsub_cmd_str += '#BSUB -o {}\n'.format(train_stdout)
            bsub_cmd_str += '#BSUB -e {}\n'.format(train_stderr)
            bsub_cmd_str += "#BSUB -n {}\n".format(args.num_nodes)
            bsub_cmd_str += "#BSUB -q {}\n".format(args.q)
            bsub_cmd_str += "#BSUB -gpu '{}'\n".format(str(args.gpus))
            bsub_cmd_str += "#BSUB -W {}\n".format(args.W)
            bsub_cmd_str +=  "#BSUB -R '{}'\n".format(args.R)

            bsub_cmd_str += "#BSUB -R 'span[hosts=1]'\n" # todo: working?

            bsub_cmd_str += "#BSUB -B\n"
            bsub_cmd_str += "#BSUB -N\n"

            # extra commands between bsub and run
            extra_cmd_str = add_extra()

            # complete joined string
            bsub_cmd_str = '#!/bin/sh\n{}\n\n{}\n\n{}\n\n\nwait $! \nsleep 610 & \nwait $!'.format(bsub_cmd_str, extra_cmd_str, run_cmd_str)


            # updating job .sh file to be submitted
            f = open("sweep_var.sh", "w")
            f.close() # cleans it
            with open('sweep_var.sh', 'a') as f:
                f.write(bsub_cmd_str)
                f.close()

        if args.dry_run:
            dry_run("start remote training")
            dry_run(f"- log stdout to: {train_stdout}")
            dry_run(f"- log stderr to: {train_stderr}")
            dry_run(f"- run command: {bsub_cmd_str}")
            with subprocess.Popen(
                bsub_cmd, stdout=subprocess.PIPE, env=env
            ) as train_proc:
                stdout = train_proc.stdout.read().decode("utf-8")
                print(stdout)
        else:
            # logging most recent git commit
            with open(train_log, "a") as train_log_h:
                git_commit = subprocess.check_output(
                    "git log | head -n 1", shell=True, encoding="utf-8"
                )
                print(git_commit.rstrip(), file=train_log_h)
                if args.baseline_model:
                    print(f"baseline model: {args.baseline_model}", file=train_log_h)

            # submitting job
            with open(train_log, "a") as train_log_h:
                print(f"running command: {bsub_cmd_str}\n")
                print(f"running command: {bsub_cmd_str}\n", file=train_log_h)  # adding to log file
                # submitting job
                with subprocess.Popen(["bsub<sweep_var.sh"], shell=True, stdout=subprocess.PIPE, env=env) as training_process:
                    stdout, stderr = training_process.communicate()
                    print(stdout, file=train_log_h)
                    try:
                        job_id = int(stdout.rstrip().split()[1][1:-1])
                        return job_id
                    except IndexError:
                        return None


def has_finished(save_dir):
    train_log = os.path.join(save_dir, "train.log")
    if not os.path.exists(train_log):
        return False
    with open(train_log) as h:
        lines = h.readlines()
        if len(lines) == 0:
            return False
        if "Finished run" in lines[-1]:
            return True
    return False


def has_failed(save_dir):
    if not os.path.exists(save_dir):
        return False

    # find max job id
    job_ids = []
    for fn in os.listdir(save_dir):
        if fn.startswith("train.stderr."):
            job_ids.append(int(fn.split(".")[-1]))
    if len(job_ids) == 0:
        return False
    max_job_id = max(job_ids)

    def _has_failed(stderr_fn):
        with open(stderr_fn) as h:
            for line in h:
                if len(line.strip()) > 0:
                    # assume that any output in stderr indicates an error
                    return True
        return False

    return _has_failed(os.path.join(save_dir, f"train.stderr.{max_job_id}"))


def has_started(save_dir):
    train_log = os.path.join(save_dir, "train.log")
    if not os.path.exists(train_log):
        return False
    return True


def get_random_port():
    old_state = random.getstate()
    random.seed()
    port = random.randint(10000, 20000)
    random.setstate(old_state)
    return port

# extra parameters in submission file
def add_extra():
    #return 'nvidia-smi\nmodule load cuda/11.1\nsource vqa2/bin/activate\ncd mmf\n'
    return 'nvidia-smi\nmodule load cuda/11.1\nsource /work3/s194253/envs/vqa/bin/activate\ncd mmf\n'

