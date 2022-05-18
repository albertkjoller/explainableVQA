#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr 25 11:14:28 2022

@author: s194253
"""

import sys, os
from pathlib import Path

import cv2
import torch
import numpy as np

from mmf.models import Qlarifais

sys.path.append(('/').join(os.getcwd().split('/')[:-1]))
from mmexp.utils.argument_wrapper import run_explainability, load_image

if __name__ == "__main__":
    
    def image_loader(old_img_name):
        # input image
        img_name = input("Enter image name from '../imgs/temp/' folder (e.g. 'rain/rain.jpg'): ")
        if old_img_name != None:
            cv2.destroyWindow(f"{old_img_name}")
    
        if img_name != 'quit()': # continues until user quits
            # load image
            img2None = False
            img_path = Path(f"./../imgs/temp/{img_name}").as_posix()
            img = cv2.imread(img_path)  # open from file object
            
            if type(img) == type(None):
                img = cv2.imread(Path("./../imgs/temp/fail.png").as_posix())
                img2None = True       
            
            # show image
            cv2.namedWindow(f"{img_name}", cv2.WINDOW_NORMAL)
            cv2.resizeWindow(f"{img_name}", 600, 300)
            cv2.imshow(f"{img_name}", img)
            cv2.waitKey(1)
            
            if img2None:
                img = None
            
            return img_name, img_path, img
        else:
            return "quit()", None, None
        
    # obtain user input
    save_dir = input("Enter directory path of saved models ('save'-folder): ")
    model_name = input("\nEnter saved model filename: ")
    path_to_torch_cache = input("\nEnter the path to where your torch-cache folder is located (e.g. /work3/s194253): ")

    model = Qlarifais.from_pretrained(f"{save_dir}/models/{model_name}", path_to_torch_cache)
    model.to(torch.device("cuda:0" if torch.cuda.is_available() else "cpu"))
    
    # initialize data variables
    old_img_name = None
    img_name, question = None, None    
    explainability_method = None    

    # continue until user quits
    while question != 'quit()':
        img = None

        print(f"\n{'-'*70}\n")
        while type(img) == type(None):
            
            img_name, img_path, img = image_loader(old_img_name)
            if img_name == 'quit()':
                break
            elif type(img) == type(None):
                print("\nImage-file does not exist - try again...\n")
            
            # update img_name
            old_img_name = img_name
        
        if img_name == 'quit()':
            cv2.destroyAllWindows()
            break
        
        elif explainability_method != None:
            cv2.destroyWindow(f"{explainability_method}")

        # input question
        question = input("\nEnter question: ")
        if question == 'quit()':
            break
        else:
            
            answer = input("\nEnter ground truth answer (from answer list): ")
            category_id = model.processor_dict['answer_processor'].word2idx(answer)
            print(f"Answer category label: {category_id}")
            
            explainability_method = input("\nEnter explainability method: ")
            image = load_image(img_path)
            
            #image_tensor = model.processor_dict["image_processor"](image)
            
            save_path = run_explainability(model, model_name, 
                                           image, img_name, 
                                           question, category_id, 
                                           explainability_method,
                                           )
            
            if explainability_method != 'MMGradientOR':
                    
                
                # show explainability image
                explainer_img = cv2.imread(save_path)  # open from file object
                cv2.namedWindow(f"{explainability_method}", cv2.WINDOW_NORMAL)
                cv2.resizeWindow(f"{explainability_method}", 600, 300)
                cv2.imshow(f"{explainability_method}", explainer_img)
                cv2.waitKey(1)
                
            else:
                # Read images
                img1 = cv2.cvtColor(cv2.imread(save_path[0]), cv2.COLOR_BGR2RGB)
                img2 = cv2.imread(save_path[1])
                
                explainer_img = np.concatenate((img1, img2), axis=0)

                # show explainability image
                cv2.namedWindow(f"{explainability_method}", cv2.WINDOW_NORMAL)
                cv2.resizeWindow(f"{explainability_method}", 600, 300)
                cv2.imshow(f"{explainability_method}", explainer_img)
                cv2.waitKey(1)
                

    # when loop is ended
    cv2.destroyAllWindows()