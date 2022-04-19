#!/usr/bin/env python3

import numpy as np
from numpy.linalg import inv, norm
from numpy.random import default_rng
from matplotlib import pyplot as plt
import matplotlib.lines as mlines
import pandas as pd
from gensim.models import Word2Vec, KeyedVectors, Doc2Vec
from gensim.models.doc2vec import TaggedDocument
from sklearn.datasets import make_biclusters
from sklearn.cluster import SpectralCoclustering, KMeans
from sklearn.metrics import silhouette_score, consensus_score, accuracy_score, adjusted_rand_score, v_measure_score, adjusted_mutual_info_score
from sklearn.datasets import make_blobs
from sklearn.feature_extraction.text import *
from sklearn.preprocessing import normalize
import nltk

from collections import Counter
import itertools
from pprint import pprint
import sys,os,pickle,re
import algorithms
from pyqtgraph.Qt import QtCore, QtGui
#import pyqtgraph.opengl as gl
import pyqtgraph as pg

wbkm = __import__("wbkm numpy debugging land")
from nbvd import NBVD_coclustering
from my_utils import *

#downloads = [nltk.download('stopwords'), nltk.download('averaged_perceptron_tagger'), nltk.download('universal_tagset')]
stop_words_nltk=nltk.corpus.stopwords.words('english')
import sklearn
np.set_printoptions(edgeitems=5, threshold=sys.maxsize,linewidth=95) # very personal preferences :)

stop_words_nltk.extend(['also','semi','multi','sub','non','et','al','like','pre','post', # preffixes
    'ltd','sa','SA','copyright','eg','etc','elsevier','springer','springer_verlag','inc','publishing', # copyright
    'g','kg','mg','mv','km','km2','cm','bpd','bbl','cu','ca','mday','yr','per', # units
    'one','two','three','four','five','six','seven','eight','nine','ten','de','within','previously','across','top','may','mainly','thus','highly','due','including','along','since','many','various','however','could', # misc 1
    'end','less','able','according','include','included','around','last','first','major','set','average','total','new','based','different','main','associated','related','regarding','approximately','others', # misc 2
    'likely','later','would','together','even','part','using','mostly','several','values', # misc 3
    'study','studies','studied','research','paper','suggests','suggest','indicate','indicates','show','shows','result','results','present','presents','presented','considering','proposed','discussed','licensee','authors','aims', # research jargon 1
    'analysis','obtained','estimated','observed','data','model','sources','revealed','found','problem','used', # research jargon 2
    #'os','nature','algorithm' # TODO: double-check
])
# false positives: Cu, Ca,

# w2v:
# 42123456 (8,5)
# 12 (4,6) dim=50
# tfidf (reduzido):
# 42 (4,4) cent_select=false
N_ROW_CLUSTERS, N_COL_CLUSTERS = 4,4
RNG_SEED=423
VECTORIZATION='tfidf'
#vec_kwargs = Bunch(min_df=4, max_df=0.98, stop_words='english')
vec_kwargs = Bunch(min_df=4, stop_words=stop_words_nltk, lowercase=False)

W2V_DIM=100
ALG='nbvd'
ATTEMPTS_MAX=1
SYMMETRIC = False # (NBVD) use symmetric NBVD algorithm?
WAIT_TIME = 4 # wait time between tasks
LABEL_CHECK = True
CENTROID_CHECK = True
COCLUSTER_CHECK = True
NORM_PLOT = False # (NBVD) display norm plot
LABELING_METHOD="centroids method" # TODO: implement changing to not fancy
CENTROID_CANDIDATE_SELECTION=False
rerun_embedding=True
MOVIE=False
ASPECT_RATIO=4 # 1/6 for w2v; 10 for full tfidf; 4 for partial
SHOW_IMAGES=False


############################################################################## 
# to use a set number of cpus: 
#   taskset --cpu-list 0-7 python "pira.py"
##############################################################################

def w2v_combine_sentences (tokenized_sentences, model, method='tfidf', isDoc2Vec=False):
    out = []
    if method == 'tfidf' and not isDoc2Vec:
        pseudo_sentences = [" ".join(token_list) for token_list in tokenized_sentences]
        vec = TfidfVectorizer()
        vec.fit(pseudo_sentences)
        idf_mapping = dict(zip(vec.get_feature_names(), vec.idf_))
    elif method == 'concat':
        max_len = max([len(sen) for sen in tokenized_sentences])

    for i,sentence in enumerate(tokenized_sentences):
        if not isDoc2Vec:
            if model.isPreTrained:
                word_vectors = np.array([model.word_to_vec_dict[word] for word in sentence if word in model.word_to_vec_dict])
            else:
                word_vectors = np.array([model.wv[model.wv.key_to_index[word]] for word in sentence])
            if method == 'sum':
                sentence_vector = np.sum(word_vectors, axis=0)
            elif method == 'mean':
                sentence_vector = np.mean(word_vectors, axis=0)
            elif method == 'tfidf':
                if not model.isPreTrained:
                    word_idfs = [idf_mapping[word] for word in sentence]
                else:
                    word_idfs = [idf_mapping[word] for word in sentence if word in model.word_to_vec_dict]
                n = word_vectors.shape[0]
                sentence_vector = np.dot(word_idfs, word_vectors)/n # average with idf as weights
            elif method == 'concat':
                #NOTE: maybe get normed vectors above and use normed vectors? 
                # normalize sentence_vector?
                flattened = word_vectors.flatten()
                pad_length = W2V_DIM*max_len - flattened.shape[0]
                # pad 'flattened' with constant zeroes, 
                #   'pad_length' times _after_ the original array and 0 times _before_ it
                #   (we're doing post-padding)
                sentence_vector = np.pad(flattened, (0, pad_length), 'constant', constant_values=0)
        else:
            sentence_vector = model.dv[i]
        out.append(sentence_vector)
    out = np.array(out)
    if method == 'concat':
        out = normalize(np.array(out), norm='l1', copy=False) #l2 didnt do much good
    return out

def dict_from_pretrained_model(path_to_embedding_file, relevant_words):
    print("Creating embedding matrix ...")
    embeddings_index = {}
    with open(path_to_embedding_file, "r") as f:
        for i, line in enumerate(f):
            if i == 0:
                n_vectors, embedding_dim = line.split()
                continue
            word, coefs = line.split(maxsplit=1)
            coefs = np.fromstring(coefs, dtype="float64", sep=" ")
            if word in relevant_words:
                embeddings_index[word] = coefs
    misses = relevant_words.difference(set(embeddings_index.keys()))
    print(f"{len(misses)} misses while converting")
    return embeddings_index

class FooClass:
    pass
exp_numbers = re.compile("[^A-Za-z]\d+\.\d+|[^A-Za-z]\d+\,\d+|[^A-Za-z]\d+")
exp_non_alpha = re.compile("[^A-Za-zÀàÁáÂâÃãÉéÊêÍíÓóÔôÕõÚúÇç02-9 \_–+]+")
exp_whitespace = re.compile("\s+")
exp_hyphen = re.compile("(?<=[a-z])\-(?=[a-z])")

# NOTES: no overly small abstracts (all greater than 300 characters); 
# some duplicates (in the abstract column)
class Preprocessor:
    def lower_but_keep_acronyms (s):
        new = []
        for w in s.split(" "):
            new.append(w if w.isupper() and len(w) >= 2 else w.lower())
        return " ".join(new)

    def preprocess (self, sentence):
        new_sentence = sentence
        new_sentence = Preprocessor.lower_but_keep_acronyms(new_sentence)
        new_sentence = re.sub(exp_hyphen, "_", new_sentence) # keep compound words in tokenization
        new_sentence = re.sub(exp_numbers, " 1", new_sentence)
        new_sentence = re.sub(exp_non_alpha, "", new_sentence)
        new_sentence = re.sub(exp_whitespace, " ", new_sentence)
        return new_sentence

    def fit(self, X, y=None, **fit_params):
        return self

    def transform(self, X, y=None, **fit_params):
        X_list = X.to_list() if type(X) != list else X
        unique_sentences = set()
        newX = []
        for i,sentence in enumerate(X_list):
            if sentence not in unique_sentences:
                unique_sentences.add(sentence)
                newX.append(self.preprocess(sentence))
        return newX

def __candidate_selection (dists_to_centroid, labels, cluster_no, n_representatives):
    count = 0
    for i, _ in dists_to_centroid:
        if labels[i] == cluster_no:
            count += 1
            yield i
        if count >= n_representatives:
            return # stop yielding

def get_representatives (data, labels, centroids, n_clusters, n_representatives=3, reverse=False) -> dict:
    cluster_representatives = {}
    if not CENTROID_CANDIDATE_SELECTION:
        centroids_ = get_centroids_by_cluster (data, labels, n_clusters)
    else:
        centroids_ = centroids
    
    # get squashed centroids and, for each sample, calculate distance to squashed_centroid
    squashed_centroids = np.sum(centroids_.T, axis=1) # squash centroids to just 1 number per cluster
    all_distances = np.zeros((data.shape[0], n_clusters))
    for i, r in enumerate(data):
        all_distances[i] = [norm(r-centroid_sum) for centroid_sum in squashed_centroids]

    # get representatives
    for c in range(n_clusters):
        dists_to_centroid = sorted(zip(list(range(data.shape[0])), list(all_distances[:,c])), 
            key = lambda t : t[1], reverse=reverse)

        # select top n; eliminate candidates that arent from the relevant cluster
        rep_candidates = list(__candidate_selection(dists_to_centroid, labels, c, n_representatives))
        if rep_candidates: # if anyones left
            cluster_representatives[c] = rep_candidates   
    return cluster_representatives

def calculate_occurrence (word, original_data, indices):
    count = 0
    for i in indices:
        if word.lower() in original_data[i].lower():
            count += 1
    return count

def cluster_summary (data, original_data, vec, model, n_doc_reps=5, n_word_reps=30, n_frequent=50, logger=None):
    print_or_log = logger.info if logger else print
    has_cocluster_info = hasattr(model, "cluster_assoc")
    row_centroids, col_centroids = model.centroids
    row_labels_, column_labels_ = model.row_labels_, model.column_labels_
    m, k = row_centroids.shape
    n, l = col_centroids.shape

    if has_cocluster_info:
        cluster_assoc = model.cluster_assoc
        assoc_shape = cluster_assoc.shape
    else:
        print_or_log("No cocluster info.")

    if has_cocluster_info:
        # get relevant coclusters
        relevant_coclusters = []
        for i in range(assoc_shape[0]):
            for j in range(assoc_shape[1]):
                if cluster_assoc[i,j]:
                    relevant_coclusters.append((i,j))
    
    # get representatives
    row_cluster_representatives = get_representatives(data, row_labels_, row_centroids, 
        k, n_representatives=n_doc_reps)
    col_cluster_representatives = get_representatives(data.T, column_labels_, col_centroids, 
        l, n_representatives=n_word_reps)

    # documents
    print_or_log("DOCUMENTS:\n")
    for i, reps in sorted(row_cluster_representatives.items()):
        print_or_log("cluster:", i)
        for rep in reps:
            print_or_log("rep:", rep)
            print_or_log(original_data[rep][:200])
        print_or_log("--------------------------------------------------------\n")

    if isinstance(vec, TfidfVectorizer):
        # word analysis
        print_or_log("WORDS:\n")
        idx_to_word = vec.get_feature_names()
        for i, c in sorted(col_cluster_representatives.items()):
            print_or_log("cluster:", i)
            to_print = []
            for rep in c:
                to_print.append(idx_to_word[rep])
            print_or_log(*to_print, sep=", ")
            print_or_log("--------------------------------------------------------\n")
        
        if has_cocluster_info:
            # cocluster analysis
            print("COCLUSTERS:")
            N = n_frequent
            # TODO: do top 10% / 20% / 25% instead?
            print(f"word (occurrence in top {N} documents)(occurrence in bottom {N} documents) (occurrence in other doc clusters)")
            row_reps_topN = get_representatives(data, row_labels_, row_centroids, 
                k, n_representatives=N)
            row_reps_bottomN = get_representatives(data, row_labels_, row_centroids, 
                k, n_representatives=N, reverse=True)
            
            # for each cocluster
            for dc, wc in relevant_coclusters:
                print("cocluster:", (dc, wc),"\n")
                to_print = []
                reps = col_cluster_representatives[wc] # get the representatives for the word cluster
                
                # for each word, calculate its occurrence in each document cluster
                for w in reps:
                    if dc not in row_reps_topN:
                        print(f"## @#@ #@ {dc} not in row_reps!!!\n")
                        continue
                    else:
                        # occurrence for the dc in the cocluster
                        word = idx_to_word[w]
                        oc_top = calculate_occurrence(word, original_data, row_reps_topN[dc])
                        oc_bottom = calculate_occurrence(word, original_data, row_reps_bottomN[dc])
                        
                        # occurrence for other dcs
                        oc_others = []
                        for r_idx in sorted(row_reps_topN.keys()):
                            if r_idx == dc:
                                continue
                            oc_other = calculate_occurrence(word, original_data, row_reps_topN[r_idx])
                            oc_others.append((r_idx, oc_other))
                        oc_other_str = "".join([f"({r_idx}:{oc_other*100/N:.0f}%)" for r_idx,oc_other in oc_others])
                        to_print.append(f"{word}(T:{oc_top*100/N:.0f}%)(B:{oc_bottom*100/N:.0f}%) {oc_other_str}")
                print(", ".join(to_print), end="\n--------------------------------------------------------\n\n")

def do_vectorization (new_abstracts, vectorization_type, **kwargs):
    if vectorization_type == 'tfidf':
        vec = TfidfVectorizer(**kwargs)
        data = vec.fit_transform(new_abstracts).toarray()
    elif vectorization == 'count':
        vec = CountVectorizer(**kwargs)
        data = vec.fit_transform(new_abstracts).toarray()
    elif vectorization_type == 'tfidf-char':
        #vec = TfidfVectorizer(ngram_range=(5,5), analyzer='char', max_features=15000)
        vec = TfidfVectorizer(ngram_range=(5,5), analyzer='char')
        data = vec.fit_transform(new_abstracts).toarray()
    elif vectorization_type == 'w2v' or vectorization_type == 'pretrained':
        embedding_dump_name = ".embedding_cache/pira.w2v" if vectorization_type == 'w2v' else ".embedding_cache/pretrained.w2v"
        vec = CountVectorizer()
        tok = vec.build_tokenizer()
        tokenize_sentence_array = lambda sentences: [tok(sentence) for sentence in sentences]
        tok_sentences = tokenize_sentence_array(new_abstracts) # frases tokenizadas (iteravel de iteraveis)
        if rerun_embedding or not os.path.isfile(embedding_dump_name):
            if vectorization_type == 'w2v':
                # NOTE: min_count=1 is not the default >:) exhilarating!
                full_model = Word2Vec(sentences=tok_sentences, vector_size=W2V_DIM, min_count=1, sg=0, window=5, workers=1, seed=42) # ligeiramente melhor mas mt pouco
                full_model.save(embedding_dump_name)
            elif vectorization_type == 'pretrained':
                vec.fit(new_abstracts)
                full_model = FooClass() # lambdas cannot be pickled apparently
                full_model.isPreTrained = True
                full_model.vocabulary = set(vec.vocabulary_.keys())
                full_model.word_to_vec_dict = dict_from_pretrained_model(path_to_embedding_file="pre-trained/cc.en.300.vec", relevant_words=full_model.vocabulary)
                with open(embedding_dump_name, "wb") as f:
                    pickle.dump(full_model, f)
        else:
            if vectorization_type == 'w2v':
                full_model = Word2Vec.load(embedding_dump_name, mmap='r')
            elif vectorization_type == 'pretrained':
                with open(embedding_dump_name, "rb") as f:
                    full_model = pickle.load(f)
        if vectorization_type == 'w2v':
            full_model.isPreTrained = False
        vec = full_model
        data = w2v_combine_sentences(tok_sentences, full_model, method='tfidf')
        
    elif vectorization_type == 'd2v':
        embedding_dump_name = ".embedding_cache/pira.d2v"
        tok = CountVectorizer().build_tokenizer()
        tokenize_sentence_array = lambda sentences: [tok(sentence) for sentence in sentences]
        tok_sentences = tokenize_sentence_array(new_abstracts) # frases tokenizadas (iteravel de iteraveis)
        if rerun_embedding or not os.path.isfile(embedding_dump_name):
            # NOTE: min_count=1 is not the default >:) exhilarating!
            documents = [TaggedDocument(sentence, [i]) for i,sentence in enumerate(tok_sentences)]
            doc_vector_size = 1*W2V_DIM
            full_model = Doc2Vec(documents=documents, vector_size=doc_vector_size, min_count=1, dm=0, window=5, workers=1, seed=42) # ligeiramente melhor mas mt pouco
            full_model.save(embedding_dump_name)
        else:
            full_model = Doc2Vec.load(embedding_dump_name, mmap='r')
        vec = full_model
        data = w2v_combine_sentences(tok_sentences, full_model, isDoc2Vec=True)

    return (data, vec)

def do_task_single (data, original_data, vectorization, only_one=True, alg=ALG, 
        show_images=True, first_image_save_path=None, RNG_SEED=None, logger=None, iter_max=2000):
    RNG = np.random.default_rng(RNG_SEED)
    # TODO: add vec to model as attribute for cleaner code

    if logger:
        logger.info(f"shape: {data.shape}")
    else:
        print(f"shape: {data.shape}")
    timer = None if only_one else WAIT_TIME * show_images 

    """
    if not only_one:
        # plot original data to build suspense AND save figure if a save path is provided
        plot_matrices([data], ["Original dataset"], timer=timer, savefig=first_image_save_path)
    """

    # do co-clustering
    if alg == 'nbvd':
        model = NBVD_coclustering(data, symmetric=SYMMETRIC, n_row_clusters=N_ROW_CLUSTERS, 
            n_col_clusters=N_COL_CLUSTERS, n_attempts=1, iter_max=iter_max, random_state=RNG_SEED, 
            verbose=False, save_history=MOVIE, save_norm_history=NORM_PLOT, logger=logger)
    elif alg == 'wbkm':
        model = wbkm.WBKM_coclustering(data, n_clusters=N_ROW_CLUSTERS, n_attempts=1,
            random_state=RNG_SEED, verbose=True, logger=logger)
    elif alg == 'spectral':
        model = SpectralCoclustering(n_clusters=N_ROW_CLUSTERS, random_state=RNG_SEED)
        model.fit(data)
    elif ALG == 'nbvd_waldyr':
        U, S, V, resNEW, itr = algorithms.NBVD(data, N_ROW_CLUSTERS, N_COL_CLUSTERS, itrMAX=2000)
        model = lambda: None
        model.U, model.S, model.V = U, S, V
        model.biclusters_, model.row_labels_, model.column_labels_ = NBVD_coclustering.get_stuff(U, V.T)
        print("resNEW, itr:", resNEW, itr) # resNEW is norm squared; itr is iteration_no
    
    # show animation of clustering process
    if MOVIE and alg == 'nbvd':
        pyqtgraph_thing(data, model, 25)

    #########################
    # evaluate results 
    #########################

    ### internal indices
    # print silhouette scores
    silhouette = print_silhouette_score(data, model.row_labels_, model.column_labels_, logger=logger)

    # textual analysis
    cluster_summary (data, original_data, vectorization, model, logger=None)

    ### DBG: testing different methods of labelling
    if alg == 'nbvd':
        _, row1, col1 = NBVD_coclustering.get_stuff(model.R, model.C, model.B, method="not fancy")
        #_, row2, col2 = NBVD_coclustering.get_stuff(model.R, model.C, model.B, method="fancy")
        _, row3, col3 = NBVD_coclustering.get_stuff(model.R, model.C, model.B, model.data, model.centroids, method="centroids")

        print("not fancy")
        silhouette2 = print_silhouette_score(data, row1, col1, logger=logger)
        #print("fancy")
        #silhouette2 = print_silhouette_score(data, row2, col2, logger=logger)
        print("centroids")
        silhouette3 = print_silhouette_score(data, row3, col3, logger=logger)
        print("rows:")
        thing = lambda arr : sorted(Counter(arr).items())
        print(thing(row1), 
            #thing(row2),
            thing(row3), sep="\n")
        #print(row1)
        #print(row2)
        #print(row3)
        print("cols:")
        print(thing(col1), 
            #thing(col2), 
            thing(col3), sep="\n")

    if show_images:
        # shade lines/columns of original dataset
        if LABEL_CHECK:
            shaded_label_matrix(data, model.row_labels_, kind="rows", method_name=LABELING_METHOD, RNG=RNG, opacity=1, aspect_ratio=ASPECT_RATIO)
            shaded_label_matrix(data, model.column_labels_, kind="columns", method_name=LABELING_METHOD, RNG=RNG, opacity=1, aspect_ratio=ASPECT_RATIO)
            if COCLUSTER_CHECK and alg == "nbvd":
                shade_coclusters(data, (model.row_labels_, model.column_labels_), 
                    model.cluster_assoc, RNG=RNG, aspect_ratio=ASPECT_RATIO)
             
        # centroid (and dataset) (normalized) scatter plot
        if CENTROID_CHECK and alg == 'nbvd':
            row_centroids, col_centroids = model.centroids[0], model.centroids[1]
            model.row_pca, model.row_c_palette, _ = centroid_scatter_plot(data, row_centroids, model.row_labels_, title="Rows and Row centroids", RNG=RNG)
            model.col_pca, model.col_c_palette, _ = centroid_scatter_plot(data.T, col_centroids, model.column_labels_, title="Columns and Column centroids", RNG=RNG)
        
        # norm evolution
        if hasattr(model, "norm_history"):
            plot_norm_history(model)

        # general plots
        if alg == 'nbvd':
            to_plot = [data, model.R@model.B@model.C]
            names = ["Original dataset", "Reconstructed matrix RBC"]
        elif alg == 'wbkm':
            to_plot = [data, model.D1@model.P@model.S@model.Q.T@model.D2, model.P@model.S@model.Q.T]
            names = ["Original dataset", "Reconstructed matrix...?", "Matrix that looks funny sometimes"]
        elif alg =="nbvd_waldyr":
            to_plot = [data, model.U@model.S@model.V.T, model.S]
            names = ["Original dataset", "Reconstructed matrix USV.T", "Block value matrix S"]
        plot_matrices(to_plot, names, timer = None if only_one else 2*timer, aspect_ratio=ASPECT_RATIO)

    # return general statistics
    if alg == 'nbvd':
        bunch = Bunch(silhouette=MeanTuple(*silhouette), 
            best_iter=model.best_iter, best_norm=model.best_norm, n_attempts=1)
    elif alg == 'wbkm':
        bunch = Bunch(silhouette=MeanTuple(*silhouette), 
            max_iter_reached=model.best_max_iter_reached, best_norm=model.best_norm,
            no_zero_cols=model.best_no_zero_cols, n_attempts=1)
    elif alg == 'spectral':
        bunch = Bunch(silhouette=MeanTuple(*silhouette), n_attempts=1)
    elif alg == 'kmeans':
        bunch = Bunch(silhouette=MeanTuple(*silhouette), n_attempts=1)
    return (model, bunch)

def load_new_new_abstracts (path, n_abstracts, old_abstracts):
    old_abstracts_S = set(old_abstracts)
    df = pd.read_csv(path, delimiter=',')
    new_new_abstracts = df['abstract'][:n_abstracts].to_list()
    new_new_not_repeat = [ab for ab in new_new_abstracts if ab not in old_abstracts_S]
    print(f"\nnew abstracts: {len(new_new_abstracts)} | repeat abstracts: {len(new_new_abstracts) - len(new_new_not_repeat)}")
    return Preprocessor().transform(new_new_not_repeat) # preprocess and eliminate duplicates

def vec_and_class_new_abstracts (extra_abstracts : Iterable, vec, model, logger=None, verbose=False):
    # TODO: clean up classification
    print_or_log = logger.info if logger else print
    row_centroids, col_centroids = model.centroids
    m, k = row_centroids.shape
    n, l = col_centroids.shape

    # vectorize abstracts
    Z = vec.transform(extra_abstracts).toarray()
    n, _ = Z.shape
    print_or_log(f"Z: {Z.shape} r_centroids: {row_centroids.shape} c_centroids: {col_centroids.shape}")

    # classify rows
    Z_row_extra = Z.reshape(*Z.shape, 1).repeat(k, axis=2) # add extra dim for clusters
    c_row_extra = row_centroids.T.reshape(k, m, 1).repeat(n, axis=2).T # add extra dim for number of samples
    row_distances = norm(Z_row_extra-c_row_extra, axis=1)
    row_classification = np.argmin(row_distances, axis=1)

    # classify columns
    Z_col_extra = Z.T.reshape(*Z.T.shape, 1).repeat(l, axis=2) # add extra dim for clusters
    c_col_extra = col_centroids.T.reshape(l, n, 1).repeat(m, axis=2).T # add extra dim for number of samples
    col_distances = norm(Z_col_extra-c_col_extra, axis=1)
    col_classification = np.argmin(col_distances, axis=1)

    # command-line results
    if verbose:
        print_or_log("\nNEW ABSTRACTS (assigned cluster and (clipped) text):")
        to_print = []
        for i,row in enumerate(extra_abstracts):
            to_print.append(f"[{row_classification[i]}]: {row[:200]}\n\n")
        print_or_log("".join(to_print))
    return (Z, row_classification, col_classification)

def new_abs_reduced_centroids_plot (model, Z, new_abs_classification, new_centroids, RNG=None):
    RNG = RNG or np.default_rng()
    # calculate reduced centroids
    row_centroids = model.centroids[0]
    print(f"@ Z:{Z.shape} labels: {new_abs_classification.shape} centroids: {row_centroids.shape}")
    _, _, ax = centroid_scatter_plot(Z, row_centroids, new_abs_classification, title="New samples and Row centroids", pca=model.row_pca, palette=model.row_c_palette, RNG=RNG)
    new_points = normalize(new_centroids.T, axis=1)
    reduced_new_points = model.row_pca.transform(new_points)

    # plot reduced points
    for i, r_centroid in enumerate(reduced_new_points):
        ax.scatter(*r_centroid, color=model.row_c_palette[i], marker="*", s=700, alpha=0.8)            
    # legends for centroid clarity
    handles = [mlines.Line2D([], [], color='black', marker='s', linestyle='None', markersize=20),
                mlines.Line2D([], [], color='black', marker='*', linestyle='None', markersize=20)]
    labels = ['Original\ncentroids', 'New data\ncentroids']
    ax.legend(handles, labels, bbox_to_anchor=(0.99,0.1), loc="lower left")
    plt.show()

def new_abs_cluster_summary (data, original_data, row_col_labels, row_col_centroids, cluster_assoc, vec, logger=None):
    model = FooClass()
    model.row_labels_, model.column_labels_ = row_col_labels
    model.centroids = row_col_centroids
    model.cluster_assoc = cluster_assoc
    cluster_summary(data, original_data, vec, model, n_word_reps=60, logger=logger)

def main():
    global RNG_SEED
    RNG, RNG_SEED = start_default_rng(seed=RNG_SEED)
    np.set_printoptions(edgeitems=5, threshold=sys.maxsize,linewidth=95) # very personal preferences :)

    # read and process
    df = pd.read_csv('pira.csv', delimiter=';')
    scientific = df[df['corpus'] == 1]
    abstracts = scientific['abstract']
    new_abstracts = Preprocessor().transform(abstracts)

    os.makedirs('.embedding_cache', exist_ok=True)
    # do co-clustering
    data, vec = do_vectorization(new_abstracts, VECTORIZATION, **vec_kwargs)

    if ATTEMPTS_MAX > 1:
        attempt = 0
        while attempt < ATTEMPTS_MAX:
            try:
                results = do_task_single(data, new_abstracts, vec, only_one = False, alg=ALG, RNG_SEED=RNG_SEED+attempt, show_images=SHOW_IMAGES)
                plt.pause(25)
            except Exception as e:
                print(str(e))
                time.sleep(2)
            finally:
                attempt += 1
    else:
        model, statistics = do_task_single(data, new_abstracts, vec, alg=ALG, iter_max=2000, RNG_SEED=RNG_SEED, show_images=SHOW_IMAGES)
        
        # analyze new abstracts
        new_new_abstracts = load_new_new_abstracts("pira_informacoes/artigosNaoUtilizados.csv", 532+13, abstracts)
        Z, new_abs_classification, new_word_classification = vec_and_class_new_abstracts(new_new_abstracts, vec, model, verbose=False)
        new_row_centroids = get_centroids_by_cluster(Z, new_abs_classification, model.n_row_clusters)
        new_col_centroids = get_centroids_by_cluster(Z.T, new_word_classification, model.n_col_clusters)
        new_abs_cluster_summary(Z, new_new_abstracts, (new_abs_classification, new_word_classification), 
            (new_row_centroids, new_col_centroids), model.cluster_assoc, vec, logger=None)
        row_dist = norm(model.centroids[0] - new_row_centroids) # frobenius norm
        col_dist = norm(model.centroids[1] - new_col_centroids) # frobenius norm
        print(f"Centroid difference for original and new abstracts:\n({row_dist}, {col_dist})")
        orig_r_clust_avg = get_centroids_by_cluster(model.data, model.row_labels_, model.n_row_clusters)
        orig_c_clust_avg = get_centroids_by_cluster(model.data.T, model.column_labels_, model.n_col_clusters)
        row_dist = norm(orig_r_clust_avg - new_row_centroids) # frobenius norm
        col_dist = norm(orig_c_clust_avg - new_col_centroids) # frobenius norm
        print(f"Centroid difference for original and new abstracts (2nd way):\n({row_dist}, {col_dist})")
        print(f"norm for original centroids: {norm(model.centroids[0])}, {norm(model.centroids[1])}")
        print(f"mean for original centroids: {np.mean(model.centroids[0])}, {np.mean(model.centroids[1])}")


        if SHOW_IMAGES:
            new_abs_reduced_centroids_plot(model, Z, new_abs_classification, new_row_centroids, RNG=RNG)

        

    """
    import itertools
    def dict_product(dicts):
        return (dict(zip(dicts, x)) for x in itertools.product(*dicts.values()))

    vec_options = ['count']
    iter_max_options = [2000, 10000]
    vec_kwargs_options = list(dict_product(dict(stop_words=["english", None], min_df=[1, 10], max_df=[1.0, 0.9], max_features=[1000, 2500, 5000, 10000])))
    full_options = [(vec, vec_kwargs, iter_max) for vec in vec_options for vec_kwargs in vec_kwargs_options for iter_max in iter_max_options]
    for vectorization, vec_kwargs, iter_max in full_options:
        print("------------------------------------------------------------")
        print(f"options:\nvectorizer: {vectorization}\nvec_kwargs: {vec_kwargs}\niter_max: {iter_max}")
        data, vec = do_vectorization(new_abstracts, VECTORIZATION, **vec_kwargs)

        os.makedirs('.embedding_cache', exist_ok=True)
        # do co-clustering
        if ATTEMPTS_MAX > 1:
            attempt = 0
            while attempt < ATTEMPTS_MAX:
                try:
                    results = do_task_single(data, new_abstracts, vec, only_one = False, alg=ALG, RNG_SEED=RNG_SEED+attempt)
                    plt.pause(25)
                except Exception as e:
                    print(str(e))
                    time.sleep(2)
                finally:
                    attempt += 1
        else:
            do_task_single(data, new_abstracts, vec, alg=ALG, iter_max=iter_max, RNG_SEED=RNG_SEED)
    """
if __name__ == "__main__":
    main()