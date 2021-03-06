#encoding=utf-8
import os
import time,datetime
import pandas as pd
import numpy as np
import random
import jieba
import keras
from keras.layers import LSTM, GRU,  Embedding, Input, Dense, TimeDistributed, Activation
from keras.models import Model, Sequential, load_model
from keras.layers.normalization import BatchNormalization
from keras.layers.core import Dropout, Reshape, Masking, Flatten, RepeatVector
from keras.utils import np_utils
from keras import backend as K
#from keras.layers.containers import Graph
#from keras.layers.merge import Dot
import word2vec

import h5py
script_dir = os.path.dirname(__file__)

jieba.load_userdict(os.path.join(script_dir, 'entity_dictionary_2_replace.txt'))
model_w2v = word2vec.load(os.path.join(script_dir, 'word2vec_corpus.bin'))
model = keras.models.load_model(os.path.join(script_dir, 'model_MTLU.h5'))
print('w2v, model loaded.')
np.random.seed(123)  # for reproducibility


len_history = 10
len_sentence = 10
dim_w2v = 100
dim_after_rnn = 100
num_tag = 5 # Nan, O , B_title, B_instructor, B_when
dim_status = 2*4+1 # request*4 and constraint*4

epochs = 5


########################################################
# turn NLP input into vector
########################################################
def sentence_to_vec(sentence, model_w2v=model_w2v, dim_w2v=dim_w2v, len_sentence=len_sentence) :
    s_vec = np.zeros((len_sentence,dim_w2v))
    if sentence == '':
        return s_vec
    sentence = sentence.split(' ')
    i3 = len_sentence - min(len(sentence), len_sentence)
    for i,word in enumerate(sentence) :
        if i3+i >= len_sentence:
            break
        if word == '' or word not in model_w2v.vocab:
            s_vec[i3+i] = [0.0] * dim_w2v
        else:
            #print(word, model_w2v[word][:4])
            # input()
            s_vec[i3+i] = model_w2v[word]
    return s_vec

########################################################
# to pretrain word2vec
########################################################
def w2v(dim_w2v=dim_w2v, data_training=None) :
    if data_training is None :
        print('nooooooo')
        return 0
    with open("word2vec_corpus.tmp", "w") as f:
            f.write(("\n".join(data_training)+"\n"))
    print('running word2vec ...')
    word2vec.word2phrase('word2vec_corpus.tmp', 'word2vec_corpus_phrases', verbose=True)
    word2vec.word2vec('word2vec_corpus_phrases', 'word2vec_corpus.bin', size=dim_w2v, verbose=True, window=5, cbow=0, binary=1, min_count=1, sample='1e-5', hs=1, iter_=5)

########################################################
# turn NLP input into vector
########################################################
def NLP_to_vec(sentence=None, len_sentence=len_sentence, model_w2v=None, dim_w2v=dim_w2v) :
    lst_seg_sentence = jieba.cut(sentence)
    ary_sentence = np.zeros((len_sentence,dim_w2v))
    t1 = 0
    if lst_seg_sentence != [''] :
        for empt in range(len_sentence - len(lst_seg_sentence)) :
            t1 += 1
        for word in lst_seg_sentence :
            if word == '' or word not in model_w2v.vocab : #or word == '' or word == '' or word == '' or word == '海口' or word == '群眾' or word == '中歸' or word == '這也能' or word == '經不住' or word == '' or word == '海天' or  word == '388' or word == '海興' or word == '彭年' or word == '場在' or word == '給凍醒' or word == '借殼'or word == '1702'or word == '1710'  or word == '剛為' or word == '568' or word == '我主':
                if t1 == 0:
                    continue
                else :
                    ary_sentence[t1] = ary_sentence[t1-1]
            else :
                ary_sentence[t1] = model_w2v[word]
            t1 += 1
    ary_sentence = ary_sentence.flatten()
    return ary_sentence

########################################################
# add current sentence into history
########################################################
def history_add(history, sentence_vec, len_history) :
    for i in range(len_history-1) :
        history[0][i] = history[0][i+1]
    history[0][len_history-1] = sentence_vec
    return history

########################################################
# X_train contains history and current sentence
# Y_train contains BIO of current sentence and intent of current sentence
########################################################
def model_MTLU(X_train_history=None, X_train_current=None, len_history=len_history, len_sentence=len_sentence,
               dim_w2v=dim_w2v, dim_after_rnn=dim_after_rnn, num_tag=num_tag, dim_status=dim_status) :
    d = 0.5 # dropout
    input_h = Input(shape=(len_history, len_sentence, dim_w2v)) # shape = (?, 8, 30 ,100)
    input_c = Input(shape=(1, len_sentence, dim_w2v)) # shape = (?, 1, 30, 100)
    rnn_s2v = GRU(dim_after_rnn)
    m = TimeDistributed(rnn_s2v)(input_h) # shape = (?, 8, 100)
    u = TimeDistributed(rnn_s2v)(input_c) # shape = (?, 1, 100)
    p_temp = keras.layers.dot([m, u], axes=-1, normalize=False) # shape = (?, 8, 1)
    p_r = Reshape((len_history, ), input_shape=(len_history, 1))(p_temp) # shape = (?, 8)

    #p_final = K.softmax(p_r) # shape = (?,8)
    p_final = Activation(K.softmax)(p_r)
    p_final_r = Reshape((len_history, 1),input_shape=(len_history, ))(p_final) # shape = (?,8,1)

    # notice not sure
    h_temp = keras.layers.multiply([p_final_r, m]) # shape = (?, 8, 100)
    #h = K.sum(h_temp, axis=1) # shape = (?, 100)
    #h = A(K.sum(h_temp, axis=1)) # shape = (?, 100)
    #h = keras.layers.add(h_temp, axis=1) # shape = (?, 100)
    h = keras.layers.pooling.AveragePooling1D(pool_size=len_history, strides=None, padding='valid')(h_temp)
    h_r = Reshape((1,dim_after_rnn), input_shape=(dim_after_rnn,))(h)
    s = keras.layers.add([h_r,u]) # shape = (?, 1, 100)
    D1 = Dense(256, activation='elu')(s)
    d1 = Dropout(d)(D1)
    D2 = Dense(128, activation='elu')(d1)
    d2 = Dropout(d)(D2)
    O = Dense(64, activation='elu')(d2) # shape = (?, 1, 64)
    #d3 = Dropout(d)(O)
    c_r = Reshape((len_sentence, dim_w2v), input_shape=(1, len_sentence,dim_w2v))(input_c) # shape = (?, 30, 100)
    O_r = Reshape((64, ),input_shape=(1, 64))(O) # shape = (?, 64)
    O_rp = RepeatVector(len_sentence)(O_r) # shape = (?, 30, 64)
    final = keras.layers.concatenate([O_rp, c_r]) # shape = (?, 30, 164)
    Y1 = GRU(num_tag, return_sequences=True, activation='softmax')(final) # shape = (?, ?, 6)
    final_flat = Flatten()(final)
    Y2 = Dense(dim_status, activation='softmax')(final_flat) # shape = (?, 8)

    model = Model(inputs=[input_h, input_c], outputs=[Y1, Y2])
    model.compile(#loss='mean_squared_error',
                  loss='categorical_crossentropy',
                  #optimizer=keras.optimizers.RMSprop(lr=0.005, rho=0.9, epsilon=1e-08, decay=0.0),
                  optimizer='adam',
                  #loss_weights=[0.1, 1.],
                  metrics=['acc']) #'mae'


    return model

    '''
    p = np.zeros((len(X_train_history),turns_history,1))
    for i in range(len(X_train_history)) :
        p[i] = keras.layers.dot([rnn_h[i],rnn_c], axes=-1)

    temp = keras.layers.multiply([rnn_h,rnn_c])
    p = keras.layers.add(temp,)

    add_input(L_input, input_shape=(8+1,max_len_sentence*dim_w2v), dtype='float')
    add_node(layer, name, input=None, inputs=[], merge_mode='concat', concat_axis=-1, dot_axes=-1, create_output=False)
    '''

# len_sentence * num_tag
# i.e. 10 * 5
# 10000:NaN 01000:O 00100:B_title 00010:B_instructor 00001:B_when
def BIO2num(BIO=None, len_sentence=len_sentence, num_tag=num_tag):
    # initialization
    lst = BIO.split(' ')
    bio_num = np.zeros((len_sentence, num_tag))
    for t in range(len(bio_num)) :
        bio_num[t][0] = 1
    n = len_sentence-len(lst)
    for i,w in enumerate(lst) :
        if w == '' :
            bio_num[n+i] = [1, 0, 0, 0, 0]
        elif w == 'O' :
            bio_num[n+i] = [0, 1, 0, 0, 0]
        elif w == 'B_title' :
            bio_num[n+i] = [0 ,0, 1, 0, 0]
        elif w == 'B_instructor' :
            bio_num[n+i] = [0, 0, 0, 1, 0]
        elif w == 'B_when' :
            bio_num[n+i] = [0, 0, 0, 0, 1]
    return bio_num


def train_MTLU(need_train_w2v=False, epochs=epochs) :
    s_log = pd.read_csv('./MTLU_template/simmulator_log.csv').fillna('')
    input()
    #all_sentence_temp = s_log['sentence']

    #training w2v
    if need_train_w2v :
        w2v(dim_w2v=dim_w2v, data_training=s_log['sentence'])
    model_w2v = word2vec.load('word2vec_corpus.bin')

    #len_group = len(s_log)/len_history
    history_group = np.zeros((len(s_log),len_history,len_sentence,dim_w2v))
    current_group = np.zeros((len(s_log),1,len_sentence,dim_w2v))
    # BIO 0: Nan 1:O 2:B_title 3:B_instructor 4:B_when
    BIO_group = np.zeros((len(s_log),len_sentence,num_tag))
    for t1 in range(len(BIO_group)) :
        for t2 in range(len_sentence) :
            BIO_group[t1][t2][0] = 1
    n = 0
    sub_turn = 0
    for b in range(0,len(s_log), 4) :
        for gg in range(4):
            history = np.zeros((len_history,len_sentence,dim_w2v))
            current = np.zeros((len_sentence,dim_w2v))
            bio_num = np.zeros((len_sentence,num_tag))
            ind = b+ gg
            s = s_log['sentence'][ind]
            if s:
                bio_num = BIO2num(s_log['BIO'][ind])
                current = sentence_to_vec(s, model_w2v, dim_w2v=dim_w2v, len_sentence=len_sentence)
                for ggg in range(gg):
                    gggs = s_log['sentence'][b+ggg]
                    #print(gggs)
                    history[4-gg+ggg] = sentence_to_vec(gggs, model_w2v, dim_w2v=dim_w2v, len_sentence=len_sentence)

            # for t1 in range(len_sentence) :
            #     bio_num[t1][0] = 1
            # n += 1
            # # 還需要改，若再多template的情況下 ^^done^^
            # if b%len_history == 0 :
            #     n = 1
            #     for s in s_log['sentence'][b:b+4] :
            #         if s == '' :
            #             n += 1
            # #print(n)
            # for i, s in enumerate(s_log['sentence'][b:b+4]):
            #     #s = s_log['sentence'][i+b]
            #     print(s, i)
            #     if i < len_history - n :
            #         history[i+n] = sentence_to_vec(s, model_w2v, dim_w2v=dim_w2v, len_sentence=len_sentence)
            #     elif i == len_history - n :
            #         current = sentence_to_vec(s, model_w2v, dim_w2v=dim_w2v, len_sentence=len_sentence)
            #         bio_num = BIO2num(s_log['BIO'][i+b])
            history_group[ind] = history
            current_group[ind] = current.reshape((1,len_sentence,dim_w2v))
            BIO_group[ind] = bio_num


    # turn s_log[status_for_MTLU] into ndarray
    # status_for_MTLU is (len(s_log),9) [[ 0 0 0 0 0 0 0 0 0],......]
    # 9 for 4*2+1
    # 4 for what who when where
    # 2 for user request or constraint
    # 1 for is_all_zero?
    temp = s_log['status_for_MTLU']
    status_for_MTLU = []
    for s in temp :
        s = s.split(' ')
        status_sub = []
        flag = 0
        for i in s :
            status_sub.append(int(i))
            if i != '0' :
                flag = 1
        if flag == 0 :
            status_sub.append(1)
        else :
            status_sub.append(0)
        status_for_MTLU.append(status_sub)
    status_for_MTLU = np.asarray(status_for_MTLU)
    #print(status_for_MTLU)

    temp = s_log['BIO']
    BIO = []
    for s in temp :
        s = s.split(' ')
        temp2 = []
        for i in s :
            temp2.append(i)
        BIO.append(temp2)

    model_mtlu = model_MTLU(history_group, current_group,
                            len_history=len_history, len_sentence=len_sentence,
                            dim_w2v=dim_w2v, dim_after_rnn=dim_after_rnn,
                            num_tag=num_tag, dim_status=dim_status)
    #print(history_group)
    #print(current_group)
    global input_history, input_current
    input_history = history_group
    input_current = current_group
    model_mtlu.fit([history_group,current_group],[BIO_group,status_for_MTLU],
                    batch_size=32, epochs=epochs, verbose=1, validation_split=0.1)
    #global prediction
    #prediction = model_mtlu.predict([history_group,current_group])
    #return model_mtlu
    model_mtlu.save('./model_MTLU.h5')

    # for some fault of compatible
    f = h5py.File('model_MTLU.h5', 'r+')
    del f['optimizer_weights']
    f.close()


########################################################
# input : history and current sentence
# output : new state which is like dia_state["inform_slots"] = {"title": key_word }
########################################################
def run_MTLU(history=None, sentence=None, old_state=None, model=model,
             model_w2v=model_w2v, len_history=len_history, len_sentence=len_sentence,
             dim_w2v=dim_w2v, dim_after_rnn=dim_after_rnn, num_tag=num_tag, dim_status=dim_status) :
    if not old_state:
        old_state = {}
        old_state["request_slots"] = {}
        old_state["inform_slots"] = {}
    # if not history:
    #    history = np.zeros((1,len_history,len_sentence,dim_w2v))

    #sentence_vec = NLP_to_vec(sentence)
    sentence = [ tok for tok in jieba.cut(sentence) if tok.strip()]
    print('run_MTLU', sentence)
    sentence_str = ' '.join(sentence)
    sentence_vec = sentence_to_vec(sentence_str, model_w2v, dim_w2v=dim_w2v)
    sentence_vec = sentence_vec.reshape((1,1,len_sentence,dim_w2v))
    prediction = model.predict([history,sentence_vec])
    #sentence_vec = sentence_vec.reshape((1,len_sentence,dim_w2v))
    #history_new = history_add(history,sentence_vec,len_history)

    dia_state = old_state
    dia_state["request_slots"] = {}
    #lst_constraint = ['title', 'instructor', 'schedule_str', 'classroom']
    temp = np.argmax(prediction[1], axis=1)
    status = temp[0] # 0~8
    temp = np.argmax(prediction[0], axis=2)
    bio = temp[0] # 0~4
    #key_word = []
    key_word = ''
    for i2,v2 in enumerate(bio) :
        if v2 == 2 or v2 == 3 or v2 == 4:
            key_word = sentence[i2-len_sentence+len(sentence)]
            print('key_word caught', key_word, i2)

    if status == 0 :
        dia_state["request_slots"] = {"title": "?"}
    elif status == 1 :
        dia_state["inform_slots"]['title'] = key_word
    elif status == 2 :
        dia_state["request_slots"] = {"instructor": "?"}
    elif status == 3 :
        dia_state["inform_slots"]['instructor'] = key_word
    elif status == 4 :
        dia_state["request_slots"] = {"schedule_str": "?"}
    elif status == 5 :
        dia_state["inform_slots"]["schedule_str"] = key_word
    elif status == 6 :
        dia_state["request_slots"] = {"classroom": "?"}
    elif status == 7 :
        dia_state["inform_slots"]["classroom"] = key_word
    else :
        print('no need action')

    return dia_state


if __name__ == '__main__' :

    model = train_MTLU(True)

    #model_w2v = word2vec.load('word2vec_corpus.bin')
