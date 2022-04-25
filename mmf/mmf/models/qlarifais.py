

import torch
from pathlib import Path
import gc
from tqdm import tqdm
from torch.nn.functional import normalize

# All model using MMF need to inherit BaseModel
from mmf.models.base_model import BaseModel
# registry is need to register the dataset or our new model so as to be MMF discoverable
from mmf.common.registry import registry
# Builder methods for image encoder and classifier
from mmf.utils.build import (
    #build_classifier_layer,
    build_image_encoder,
    build_text_encoder,
    build_graph_encoder,
    build_fusion_module,
    build_classifier,
    build_attention_module
    )

from mmf.utils.text import VocabDict

from mmf.modules.prior import load_priors


'''
run commands:

# default:
mmf_run config='configs/experiments/defaults.yaml' model=qlarifais dataset=okvqa run_type=train_val

# simple fast
mmf_run config='configs/experiments/baseline/multiply.yaml' model=qlarifais dataset=okvqa run_type=train_val


# image features example:
mmf_run config='configs/experiments/image_encoder/grids.yaml' model=qlarifais dataset=okvqa run_type=train_val

# classifier example:
#   - define image encoder in experiment folder configs
mmf_run config='configs/experiments/classifier/sigmoid.yaml' model=qlarifais dataset=okvqa run_type=train_val

Fusion
mmf_run config='configs/experiments/fusion/concat.yaml' model=qlarifais dataset=okvqa run_type=train_val

# attention example:
#   - define image encoder in experiment folder configs
mmf_run config='configs/experiments/attention/ques_graph_guided.yaml' model=qlarifais dataset=okvqa run_type=train_val


'''

# Register the model for MMF, "concat_bert_tutorial" key would be used to find the model
@registry.register_model("qlarifais")
class Qlarifais(BaseModel):
    # All models in MMF get first argument as config which contains all
    # of the information you stored in this model's config (hyperparameters)
    def __init__(self, config):
        # This is not needed in most cases as it just calling parent's init
        # with same parameters. But to explain how config is initialized we
        # have kept this
        super().__init__(config)
        self.build()

    # This classmethod tells MMF where to look for default config of this model
    @classmethod
    def config_path(cls):
        # Relative to user dir root
        return "configs/models/qlarifais/defaults.yaml"

    # Each method need to define a build method where the model's modules
    # are actually build and assigned to the model
    def build(self):

        # building general modules
        self.vision_module = build_image_encoder(self.config.image_encoder)
        self.language_module = build_text_encoder(self.config.text_encoder)
        self.fusion_module = build_fusion_module(self.config.fusion)
        self.classifier = build_classifier(self.config.classifier)


        # external knowledge
        if self.config.graph_encoder.use:
            self.graph_encoder = build_graph_encoder(self.config.graph_encoder)

        # attention
        if self.config.attention.use:
            # initiating attention module
            self.attention_module = build_attention_module(attention_config)



    def forward(self, sample_list):

        # QUESTION EMBEDDINGS
        # text input features will be in "input_ids" key
        question = sample_list["input_ids"]
        # get the text and image features from the encoders
        question_features = self.language_module(question)


        # IMAGE FEATURES
        image = sample_list["image"]
        image_features = self.vision_module(image) # [batch_size, i_dim, sqrt(max_features), sqrt(max_features)] # TODO: ?


        # GRAPH EMBEDDINGS
        if self.config.graph_encoder.use:
            sample_list["q_encoded"] = question # dim 128
            graph_features = self.graph_encoder(sample_list) # [batch_size, g_dim]


        # ATTENTION
        if self.config.attention.use:
            # getting correct input shape
            image_features = image_features.flatten(2,3).permute(0, 2, 1) # [batch_size, num_features, i_dim]
            # extracting attention based on defined attention mechanism
            if self.config.attention.type == 'question_guided':
                attention = self.attention_module(image_features, question_features)
            if self.config.attention.type == 'graph_guided':
                attention = self.attention_module(image_features, graph_features)
            if self.config.attention.type == 'question_graph_guided':
                attention = self.attention_module(image_features, question_features, graph_features)
            # [batch_size, num_features, 1]
            # weighted average of image features
            image_features = (attention * image_features).sum(1)  # [batch_size, i_dim]
        # if not using attention
        else:
            if self.config.image_encoder.resize == 'average_pooling':
                # average pool K features of size 2048
                image_features = torch.mean(image_features, dim = (2,3)) # [batch_size, i_dim]


        # FUSION
        # type of fusion based on inputs
        if self.config.graph_encoder.use:
            fused_features = self.fusion_module(image_features, question_features, graph_features)
        else:
            fused_features = self.fusion_module(image_features, question_features)
        # [batch_size, answer_vocab_dim]

        # CLASSIFICATION
        logits = self.classifier(fused_features)
        output = {"scores": logits}
        # MMF will automatically calculate loss
        return output



