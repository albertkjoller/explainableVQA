#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May 24 20:16:46 2022

@author: s194253
"""

import sys, os
from pathlib import Path

import numpy as np
import glob

import torch
import cv2

from mmf.models import Qlarifais

sys.path.append("..")
from mmexp.utils.tools import str_to_class, get_input, load_image
from mmexp.utils.argument_wrapper import run_explainability, run_method

import argparse
import logging

def get_args():
    parser = argparse.ArgumentParser(description='Script for running explainableVQA-analyses.')
    parser.add_argument(
        "--model_dir",
        required=True,
        help="path to the directory with desired model name",
    )    
    parser.add_argument(
        "--torch_cache",
        required=True,
        help="path to your torch cache directory, where the dataset is stored",
    )
    parser.add_argument(
        "--protocol_dir",
        required=True,
        help="path to your torch cache directory, where the dataset is stored",
    )
    parser.add_argument(
        "--protocol_name",
        required=True,
        help="path to your torch cache directory, where the dataset is stored",
    )
    parser.add_argument(
        "--report_dir",
        help="directory path to where the model-predictions are stored.",
        default=None,
    )
    parser.add_argument(
        "--save_path",
        required=True,
        help="where to store output of the  analysis run.",
        default=None,
    )
    parser.add_argument(
        "--explainability_methods",
        nargs='+',
        help="list of explainability methods to be used, i.e. ['Gradient', 'GradCAM'].",
        default='Gradient',
    )  
    parser.add_argument(
        "--analysis_type",
        nargs='+',
        help="which analysis type to apply, e.g. 'OR', 'VisualNoise' or 'TextualNoise",
        default=None,
    )
    parser.add_argument(
        "--show_all",
        help="whether to save a combined image of the explainability methods",
        default='True',
    )    
    return parser.parse_args()


def init_logger(args):
    
    # Create logging directory
    os.makedirs(args.save_path, exist_ok=True)
    
    # Create and configure logger
    logging.basicConfig(filename=f"{args.save_path}/explainer.log",
                        format='%(asctime)s %(message)s',
                        filemode='w')
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
     
    # Setup info
    logger.info(f"\n{'-'*100}\n{'-'*100}\nRunning explainer-script for {args.model_dir.split('/')[-1]}\n{'-'*100}\n{'-'*100}\n")
                
    return logger

if __name__ == '__main__':
    
    # --model_dir /work3/s194262/save/models/optimized/baseline_ama --torch_cache /work3/s194253 --report_dir /work3/s194253/results/baseline_ama/reports --save_path /work3/s194253/results/baseline_ama --protocol_dir /work3/s194262/protocol --analysis_type OR VisualNoise TextualNoise --explainability_methods MMGradient --protocol_name pilotQ.txt --show_all True 
    
    # Get input
    args = get_args()
    args.show_all = args.show_all == 'True'
    args.analysis_type.insert(0, 'Normal')
    
    protocol_dict = get_input(args.protocol_dir, args.protocol_name)

    # Load model
    model = Qlarifais.from_pretrained(args.model_dir, args.torch_cache)
    model.to(torch.device("cuda:0" if torch.cuda.is_available() else "cpu"))
    model_name = args.model_dir.split("/")[-1]
    
    # Initialize logger
    logger = init_logger(args)
    
    # Image directory
    imgs_dir = Path(args.protocol_dir) / 'imgs'
    
    # Loop through protocol items
    for i, input_set in protocol_dict.items():
        # Load input
        answer = input_set.get('A', None)
        question = input_set.get('Q', None)
        image_name = input_set.get('I', None).lower()
        remove_object = input_set.get('R', None)
        
        # Load image
        image_path = imgs_dir / image_name.split(".")[0]
        image = load_image((image_path / image_name).as_posix())
        
        # Run explainability if answer is in answer vocab
        cat_id = model.processor_dict['answer_processor']
        category_id = cat_id.word2idx(answer)
        if category_id == 0:
            logger.warning(f"\nThe ground truth '{answer}'not found in answer vocab - skipping...\n")
        else:
            logger.info("\nRunning explainability protocol...\n")
            
            # Run explainability methods
            for explainability_method in args.explainability_methods:             
                # Create exp-method object
                method = str_to_class(explainability_method)
                
                logger.info(f'\n\n\n\nPREDICTIONS: \n\nQuestion: "{question}"\nImage: {image_name}\nAnswer: {answer}\n')
                
                # Choose analysis types
                for analysis_type in args.analysis_type:
                    if analysis_type == 'Normal':
                        mod_image = image
                        mod_question = question
                        analysis_num = 0
                        
                        # Add predictions to report
                        prediction_str = f'\nPredicted outputs from the model ({analysis_type}):\n'
                        outputs = model.classify(image=mod_image, text=mod_question, top_k=5)
                        for i, (prob, ans) in enumerate(zip(*outputs)):
                            prediction_str += f"{i+1}) {ans} \n" #"\t ({prob})\n"
                        logger.info(prediction_str)
                        
                        # predicted category
                        category_id = cat_id.word2idx(outputs[1][0])

                        # Run xplainability
                        save_name = Path(args.save_path) / f"explainability/{explainability_method}/{image_name.split('.')[0]}/{question.strip('?').replace(' ', '_').lower()}/{analysis_num}_{analysis_type.lower()}"
                        run_method(model, model_name, 
                                   mod_image, image_name, 
                                   mod_question, category_id, 
                                   explainability_method,
                                   save_path=save_name.as_posix(),
                                   analysis_type=analysis_type,
                                   )
                        
                    elif analysis_type == 'OR' and remove_object != None:
                        # Remove object                        
                        removal_path = Path(args.protocol_dir) / f'removal_results/{image_name.split(".")[0]}/{remove_object}'
                        if not os.path.exists(removal_path):
                            os.makedirs(removal_path, exist_ok=True)
                            
                            # remove objects from image
                            OR = str_to_class('OR')
                            OR_model = OR(image_path=(image_path / image_name).as_posix(),
                                          save_path=removal_path.as_posix(),
                                          obj=remove_object,
                                          num=3)
                            
                            OR_model.remove_object()
                            OR = None # For recursion
                        
                        # Load modified image
                        mod_image = load_image((removal_path / image_name).as_posix())
                        mod_question = question
                        analysis_num = 1
                        
                        # Add predictions to report
                        prediction_str = f'\nPredicted outputs from the model ({analysis_type}):\n'
                        outputs = model.classify(image=mod_image, text=mod_question, top_k=5)
                        for i, (prob, ans) in enumerate(zip(*outputs)):
                            prediction_str += f"{i+1}) {ans} \n" #"\t ({prob})\n"
                        logger.info(prediction_str)
                        
                        # predicted category
                        category_id = cat_id.word2idx(outputs[1][0])
                        
                        # Run xplainability
                        save_name = Path(args.save_path) / f"explainability/{explainability_method}/{image_name.split('.')[0]}/{question.strip('?').replace(' ', '_').lower()}/{analysis_num}_{analysis_type.lower()}"
                        run_method(model, model_name, 
                                   mod_image, image_name, 
                                   mod_question, category_id, 
                                   explainability_method,
                                   save_path=save_name.as_posix(),
                                   analysis_type=analysis_type,
                                   )

                    elif analysis_type == 'VisualNoise':
                                   
                        VisualNoise = str_to_class('VisualNoise')
                        mod_image = VisualNoise(image)
                        mod_question = question
                        analysis_num = 2
                        
                        # Add predictions to report
                        prediction_str = f'\nPredicted outputs from the model ({analysis_type}):\n'
                        outputs = model.classify(image=mod_image, text=mod_question, top_k=5)
                        for i, (prob, ans) in enumerate(zip(*outputs)):
                            prediction_str += f"{i+1}) {ans} \n" #"\t ({prob})\n"
                        logger.info(prediction_str)
                        
                        # predicted category
                        category_id = cat_id.word2idx(outputs[1][0])

                        # Run xplainability
                        save_name = Path(args.save_path) / f"explainability/{explainability_method}/{image_name.split('.')[0]}/{question.strip('?').replace(' ', '_').lower()}/{analysis_num}_{analysis_type.lower()}"
                        run_method(model, model_name, 
                                   mod_image, image_name, 
                                   mod_question, category_id, 
                                   explainability_method,
                                   save_path=save_name.as_posix(),
                                   analysis_type=analysis_type,
                                   )
                        
                    elif analysis_type == 'TextualNoise':
                        
                        TextualNoise = str_to_class('TextualNoise')
                        mod_image = image
                        mod_question = TextualNoise(question, model)
                        analysis_num = 3
                        
                        # Add predictions to report
                        prediction_str = f'\nPredicted outputs from the model ({analysis_type}):\n'
                        outputs = model.classify(image=mod_image, text=mod_question, top_k=5)
                        for i, (prob, ans) in enumerate(zip(*outputs)):
                            prediction_str += f"{i+1}) {ans} \n" #"\t ({prob})\n"
                        logger.info(prediction_str)
                        
                        # predicted category
                        category_id = cat_id.word2idx(outputs[1][0])

                        # Run xplainability
                        save_name = Path(args.save_path) / f"explainability/{explainability_method}/{image_name.split('.')[0]}/{question.strip('?').replace(' ', '_').lower()}/{analysis_num}_{analysis_type.lower()}"
                        run_method(model, model_name, 
                                   mod_image, image_name, 
                                   mod_question, category_id, 
                                   explainability_method,
                                   save_path=save_name.as_posix(),
                                   analysis_type=analysis_type,
                                   )
                        
                    else:
                        if remove_object != None:
                            logger.warning(f"Analysis type - {analysis_type} - is not implemented...")
                            raise NotImplementedError(f"Analysis type - {analysis_type} - is not implemented...")
                    
                if args.show_all == True:
                    
                    where = Path(args.save_path) / f"explainability/{explainability_method}/{image_name.split('.')[0]}/{question.strip('?').replace(' ', '_').lower()}/*"
                    explainer_img = None
                    filenames_imgs = glob.glob(where.as_posix())
                    for i, file in enumerate(sorted(filenames_imgs)):
                        if file.split("/")[-1] != 'combined.png':
                            read_img = cv2.imread(file) #orig
                            
                            try:
                                if explainer_img == None:
                                    explainer_img = read_img
                            except ValueError:
                                explainer_img = np.concatenate((explainer_img, read_img), axis=0)


                    # SAVE
                    combined_filename = ("/").join(where.as_posix().split("/")[:-1]) + '/combined.png'
                    cv2.imwrite(combined_filename, explainer_img)
            
        
        
                    
        
        