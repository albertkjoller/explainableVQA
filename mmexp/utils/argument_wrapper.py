#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun May  8 19:11:06 2022

@author: s194253
"""

from pathlib import Path
import matplotlib.pyplot as plt

from mmexp.methods import *
from mmexp.utils.visualize import plot_example
from mmexp.utils.tools import load_image, str_to_class



def run_method(model, model_name, 
               image, image_name, 
               question, category_id, 
               explainability_method,
               save_path,
               analysis_type):
    
    # Answer vocabulary
    answer_vocab = model.processor_dict['answer_processor'].answer_vocab.word_list
    
    # Get saliency map
    method = str_to_class(explainability_method)
    saliency = method(model, 
                      image,
                      question,
                      category_id,
                      )
    # visualize gradient map
    #plt.subplot(212)
    plot_example(model.image_tensor[:, [2, 1, 0]], 
                 saliency, 
                 method=explainability_method, 
                 category_id=category_id,
                 answer_vocab=answer_vocab,
                 show_plot=False,
                 save_path=save_path + '.png',
                 analysis_type=analysis_type,
                 )


def run_explainability(model, model_name, image, img_name, question, category_id, explainability_method):
    
    # Specify answer vocab and save path
    answer_vocab = model.processor_dict['answer_processor'].answer_vocab.word_list
    save_path = f"./../imgs/explainability/{model_name}/{explainability_method}/{img_name.split('/')[0]}/{question.replace(' ', '_')}"
    
    if explainability_method.split("-")[0] != 'OR':
        method = str_to_class(explainability_method)
        saliency = method(model, 
                          image,
                          question,
                          category_id,
                          )
        # visualize gradient map
        plot_example(model.image_tensor[:, [2, 1, 0]], 
                     saliency, 
                     method=explainability_method, 
                     category_id=category_id,
                     answer_vocab=answer_vocab,
                     show_plot=False,
                     save_path=save_path + '.png',
                     )
        save_path = save_path + '.png'
    
    else: # if OR
        explainability_method = explainability_method.split("-")[1]
            
        # get gradient of original image
        method = str_to_class(explainability_method)
        saliency_orig = method(model, 
                               image,
                               question,
                               category_id,
                               )
        # visualize gradient map
        plt.subplot(211)
        plot_example(model.image_tensor[:, [2, 1, 0]], 
                     saliency_orig, 
                     method=explainability_method, 
                     category_id=category_id,
                     answer_vocab=answer_vocab,
                     show_plot=False,
                     save_path=save_path + '.png',
                     )
        
        # remove objects from image
        OR = str_to_class('OR')
        OR_model = OR(img_name)
        OR_model.remove_object()
        
        # Load new image
        img_path = Path(f"./../imgs/removal_results/{OR_model.object_name}/{img_name.split('/')[-1]}").as_posix()
        modified_image = load_image(img_path)
        saliency_modified = method(model, 
                                   modified_image,
                                   question,
                                   category_id,
                                   )
        # visualize gradient map
        plt.subplot(212)
        plot_example(model.image_tensor[:, [2, 1, 0]], 
                     saliency_modified, 
                     method=explainability_method, 
                     category_id=category_id,
                     answer_vocab=answer_vocab,
                     show_plot=False,
                     save_path=save_path + f'_removed_{OR_model.object_name}.png',
                     )
        save_path = [save_path + '.png', save_path + f'_removed_{OR_model.object_name}.png']
    
    """
    # Run explainability method
    if explainability_method == 'MMEP':
        
        method = str_to_class(explainability_method)
        saliency, hist, x, summary, conclusion = method(model,
                                                        image_tensor,
                                                        image,
                                                        question,
                                                        category_id,
                                                        max_iter=50,
                                                        )
        plot_example(model.image_tensor, 
                     saliency, 
                     method=explainability_method, 
                     category_id=category_id,
                     answer_vocab=answer_vocab,
                     show_plot=False,
                     save_path=save_path + '.png',
                     )
    """  
    
    return save_path
