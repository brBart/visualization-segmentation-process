from __future__ import print_function
from keras.models import Model
from keras.callbacks import ModelCheckpoint, LearningRateScheduler
from keras.preprocessing.image import ImageDataGenerator
from keras.backend.tensorflow_backend import set_session
import tensorflow as tf
import keras
import cv2
import numpy as np
import os, errno
from glob import glob
import argparse
import random
import math

from model import get_unet_1class
from model import get_unet, get_fcn8
import callbacks

class TrainModel:
    def __init__(self, flag):
        self.flag = flag

    def select_labels(self, gt):
        human = np.where(gt==24,10,0) + np.where(gt==25,10,0)
        car = np.where(gt==26,20,0) + np.where(gt==27,20,0) + np.where(gt==28,20,0)
        road = np.where(gt==7,30,0) #+ np.where(gt==8,30,0)

        gt_new = road + car + human
        return gt_new
    
    def make_regressor_label(self, gt):
        human = np.where(gt==24,255,0) + np.where(gt==25,255,0)
        car = np.where(gt==26,255,0) + np.where(gt==27,255,0) + np.where(gt==28,20,0)
        road = np.where(gt==7,255,0) #+ np.where(gt==8,1,0)
        label = np.concatenate((human, car, road), axis=-1)
        return label

    def train_generator_multiclass(self, image_generator, mask_generator):
        while True:
            image = next(image_generator)
            mask = next(mask_generator)
            label = self.make_regressor_label(mask).astype(np.float32)
            yield (image, label)

    def train_generator(self, image_generator, mask_generator):
        while True:
            yield(next(image_generator), next(mask_generator))

    def lr_step_decay(self, epoch):
        init_lr = self.flag.initial_learning_rate
        lr_decay = self.flag.learning_rate_decay_factor
        epoch_per_decay = self.flag.epoch_per_decay
        lrate = init_lr * math.pow(lr_decay, math.floor((1+epoch)/epoch_per_decay))
        # print lrate
        return lrate

    def train(self):

        # img_size = self.flag.image_height
        batch_size = self.flag.batch_size
        epochs = self.flag.total_epoch

        datagen_args = dict(featurewise_center=False,  # set input mean to 0 over the dataset
                samplewise_center=False,  # set each sample mean to 0
                featurewise_std_normalization=False,  # divide inputs by std of the dataset
                samplewise_std_normalization=False,  # divide each input by its std
                zca_whitening=False,  # apply ZCA whitening
                rotation_range=5,  # randomly rotate images in the range (degrees, 0 to 180)
                width_shift_range=0.05,  # randomly shift images horizontally (fraction of total width)
                height_shift_range=0.05,  # randomly shift images vertically (fraction of total height)
                # fill_mode='constant',
                # cval=0.,
                horizontal_flip=False,  # randomly flip images
                vertical_flip=False)  # randomly flip images

        image_datagen = ImageDataGenerator(**datagen_args)
        mask_datagen = ImageDataGenerator(**datagen_args)

        ### generator
        seed = random.randrange(1, 1000)
        image_generator = image_datagen.flow_from_directory(
                    os.path.join(self.flag.data_path, 'train/IMAGE'),
                    class_mode=None, seed=seed, batch_size=batch_size, 
                    target_size=(self.flag.image_height, self.flag.image_width),
                    color_mode='rgb')
        mask_generator = mask_datagen.flow_from_directory(
                    os.path.join(self.flag.data_path, 'train/GT'),
                    class_mode=None, seed=seed, batch_size=batch_size, 
                    target_size=(self.flag.image_height, self.flag.image_width),
                    color_mode='grayscale')
        
        ### gpu config
        config = tf.ConfigProto()
        # config.gpu_options.per_process_gpu_memory_fraction = 0.9
        config.gpu_options.allow_growth = True
        set_session(tf.Session(config=config))

        ### define model

        model = get_unet(self.flag)
        # model = get_unet_1class(self.flag)
        
        if self.flag.pretrained_weight_path != None:
            model.load_weights(self.flag.pretrained_weight_path)
        
        ### model save
        if not os.path.exists(os.path.join(self.flag.ckpt_dir, self.flag.ckpt_name)):
            mkdir_p(os.path.join(self.flag.ckpt_dir, self.flag.ckpt_name))
        model_json = model.to_json()
        with open(os.path.join(self.flag.ckpt_dir, self.flag.ckpt_name, 'model.json'), 'w') as json_file:
            json_file.write(model_json)
        
        ### define callback function
        vis = callbacks.trainCheck(self.flag)
        model_checkpoint = ModelCheckpoint(
                    os.path.join(self.flag.ckpt_dir, self.flag.ckpt_name,'weights.{epoch:03d}.h5'), 
                    period=self.flag.total_epoch//10)
        learning_rate = LearningRateScheduler(self.lr_step_decay)
        
        ### train model
        model.fit_generator(
            #self.train_generator(image_generator, mask_generator),
            self.train_generator_multiclass(image_generator, mask_generator),
            steps_per_epoch= image_generator.n // batch_size,
            epochs=epochs,
            callbacks=[model_checkpoint, learning_rate, vis]
        )

def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: #Python > 2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else : raise