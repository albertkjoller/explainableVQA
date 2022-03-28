import os, gc
from pathlib import Path
from argparse import Namespace

import torch
import torch.nn.functional as F

from mmf.common.registry import registry
from mmf.common.sample import Sample, SampleList
from mmf.utils.env import setup_imports
from mmf.utils.configuration import Configuration
from mmf.models import *
from mmf.utils.build import build_processors

from model_utils.config import loadConfig
from model_utils.image import openImage
from model_utils.modeling import _multi_gpu_state_to_single

setup_imports()

class PretrainedModel:
    global ROOT_DIR
    ROOT_DIR = os.getcwd()

    def __init__(self, model_filename: str, ModelClass: type(BaseModel), dataset: str):
        self.model_filename = model_filename
        self.model_name = ('_').join(self.model_filename.split('_')[:-1])  # model is saved as "model_name_final.pth"
        self.ModelClass = ModelClass
        self.dataset = dataset

        self._init_processors()
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.vqa_model = self._build_vqa_model()

    def _init_processors(self):
        # define arguments
        args = Namespace()

        #TODO: change when debugging is not necessary anymore
        if os.getcwd().split(os.sep)[-1] == 'mmf': # TODO: Remove when not debuggin
            config_path = Path(f'{ROOT_DIR}/save/models/first_model/config.yaml')
        else:
            config_path = Path(f'{ROOT_DIR}/mmf/save/models/first_model/config.yaml')

        args.opts = [
            f"config={config_path}",
            f"datasets={self.dataset}",
            f"model={self.model_name}",
            "evaluation.predict=True",
        ]
        args.config_override = None

        # read configurations
        configuration = Configuration(args=args)
        config = self.config = configuration.config
        dataset_config = config.dataset_config[self.dataset]

        # update .cache paths (different from the computer on which model was trained)
        cache_dir = str(Path.home() / '.cache/torch/mmf')
        data_dir = str(Path(cache_dir + '/data/datasets'))
        config.env.cache_dir, config.env.data_dir, dataset_config.data_dir = cache_dir, \
                                                                             str(Path(cache_dir + '/data')), \
                                                                             data_dir

        # update filepaths for dataset configuration processors
        dcp = dataset_config.processors
        dcp.text_processor.params.vocab.vocab_file = str(Path(f'{data_dir}/{dcp.text_processor.params.vocab.vocab_file}'))
        dcp.answer_processor.params.vocab_file = str(Path(f'{data_dir}/{dcp.answer_processor.params.vocab_file}'))

        # add processors
        processors = self.processors = build_processors(dataset_config.processors)
        self.text_processor = processors['text_processor']
        self.answer_processor = processors['answer_processor']
        self.image_processor = processors['image_processor']

    def _build_vqa_model(self):
        # load configuration and create model object
        config = loadConfig(self.model_filename)
        model = self.ModelClass(config)

        #TODO: change when debugging is not necessary anymore
        # specify path to saved model (depending on debugging or running from command line)
        if os.getcwd().split(os.sep)[-1] == 'mmf': #TODO: remove when not debuggin
            model_path = Path(f"{ROOT_DIR}/save/models/{self.model_name}/{self.model_filename}.pth")
        else:
            model_path = Path(f"{ROOT_DIR}/mmf/save/models/{self.model_name}/{self.model_filename}.pth")

        # load state dict and eventually convert from multi-gpu to single
        state_dict = torch.load(model_path)
        if list(state_dict.keys())[0].startswith('module') and not hasattr(model, 'module'):
            state_dict = _multi_gpu_state_to_single(state_dict)

        # load state dict to model
        model.load_state_dict(state_dict)
        model.to(self.device)
        model.eval()
        return model

    def predict(self, image_path, question, topk=5):
        with torch.no_grad():
            # create sample object - required for model input
            sample = Sample()

            # process text input
            processed_text = self.text_processor({'text': question})
            sample.input_ids = processed_text['input_ids']
            sample.text_len = len(processed_text['tokens'])

            # process image input
            processed_image = self.image_processor({'image': openImage(image_path)})
            sample.image = processed_image['image']

            # gather in sample list
            sample_list = SampleList([sample]).to(self.device)

            # predict scores with model (multiclass)
            scores = self.vqa_model(sample_list)["scores"]
            scores = torch.nn.functional.softmax(scores, dim=1)

            # extract probabilities and answers for top k predicted answers
            scores, indices = scores.topk(topk, dim=1)
            topK = [(score.item(), self.answer_processor.idx2word(indices[0][idx].item())) for (idx, score) in enumerate(scores[0])]

            probs, answers = list(zip(*topK))

        # clean - garbage collection :TODO: why is this?
        gc.collect()
        torch.cuda.empty_cache()

        return probs, answers

if __name__ == '__main__':
    import sys, cv2

    # helper function for input
    def str_to_class(classname):
        return getattr(sys.modules['mmf.models'], classname)

    # obtain user input
    model_filename = input("Enter saved model filename: ")
    ModelClass = input("Enter model type (e.g. BaseModel): ")
    dataset = input("Enter name of dataset used for training: ")
    print("")

    # specify model arguments and load model
    kwargs = {'model_filename': model_filename,
              'ModelClass': str_to_class(ModelClass),
              'dataset': dataset}
    model = PretrainedModel(**kwargs)

    # only when debugging - from bash this doesn't matter #TODO: remove in the end
    if os.getcwd().split(os.sep)[-1] != 'explainableVQA':
        os.chdir(os.path.dirname(os.getcwd()))

    # initialize data variables
    old_img_name = None
    img_name, question = None, None

    # continue until user quits
    while question != 'quit()':
        print(f"\n{'-'*70}\n")

        # input image
        img_name = input("Enter image name from '../imgs/temp' folder (e.g. 'rain.jpg'): ")
        if old_img_name != None:
            cv2.destroyWindow(f"{old_img_name}")

        if img_name != 'quit()': # continues until user quits
            # load image
            img_path = Path(f"{os.getcwd()}/imgs/temp/{img_name}").as_posix()
            img = cv2.imread(img_path)  # open from file object

            # calculate the 50 percent of original dimensions
            width = int(img.shape[1] * 0.2)
            height = int(img.shape[0] * 0.2)

            # show image
            cv2.namedWindow(f"{img_name}", cv2.WINDOW_NORMAL)
            cv2.resizeWindow(f"{img_name}", width, height)
            cv2.imshow(f"{img_name}", img)
            cv2.waitKey(1)
        else:
            break

        # input question
        question = input("Enter question: ")


        # get predictions and show input
        topk = 5
        outputs = model.predict(image_path=img_path, question=question, topk=topk)
        old_img_name = img_name

        # print answers and probabilities
        print(f'\nQuestion: "{question}"')
        print("\nPredicted outputs from the model:")
        for i, (prob, answer) in enumerate(zip(*outputs)):
            print(f"{i+1}) {answer} \t ({prob})")

    # when loop is ended
    cv2.destroyAllWindows()