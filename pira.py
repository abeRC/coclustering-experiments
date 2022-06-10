#!/usr/bin/env python3

import numpy as np
from numpy.linalg import inv, norm
from numpy.random import default_rng
import math
from matplotlib import pyplot as plt
import matplotlib.lines as mlines
import pandas as pd
from gensim.models import Word2Vec, KeyedVectors, Doc2Vec
from gensim.models.doc2vec import TaggedDocument
from sklearn.datasets import make_biclusters
from sklearn.cluster import KMeans, SpectralClustering
from sklearn.metrics import silhouette_score, consensus_score, accuracy_score, adjusted_rand_score, v_measure_score, adjusted_mutual_info_score
from sklearn.datasets import make_blobs
from sklearn.feature_extraction.text import *
from sklearn.preprocessing import normalize
import nltk

from collections import Counter, OrderedDict # OrderedDict is redundant as of Python 3.7
import sys,os,pickle,re
from pyqtgraph.Qt import QtCore, QtGui
#import pyqtgraph.opengl as gl
import pyqtgraph as pg

wbkm = __import__("wbkm numpy debugging land")
from nbvd import NBVD_coclustering
from my_utils import *

#downloads = [nltk.download('stopwords'), nltk.download('averaged_perceptron_tagger'), nltk.download('universal_tagset')]
stop_words_nltk=nltk.corpus.stopwords.words('english')

stop_words_nltk.extend(['also','semi','multi','sub','non','et','al','like','pre','post', # preffixes
    'ltd','sa','SA','copyright','eg','etc','elsevier','springer','springer_verlag','inc','publishing','reserved', # copyright
    'g','m','kg','mg','mv','km','km2','cm','bpd','bbl','cu','ca','mday','yr','per', # units
    'th','one','two','three','four','five','six','seven','eight','nine','ten','de','within','previously','across','top','may','mainly','thus','highly','due','including','along','since','many','various','however','could', # misc 1
    'end','less','able','according','include','included','around','last','first','major','set','average','total','new','based','different','main','associated','related','regarding','approximately','others', # misc 2
    'likely','later','would','together','even','part','using','mostly','several','values','important','although', # misc 3
    'study','studies','studied','research','paper','suggests','suggest','indicate','indicates','show','shows','result','results','present','presents','presented','consider','considered','considering','proposed','discussed','licensee','authors','aims', # research jargon 1
    'analysis','obtained','estimated','observed','data','model','sources','revealed','found','problem','used','article', # research jargon 2
    #'os','nature','algorithm','poorly','strongly','rights','universidade', # TODO: double-check
    # TODO: regex for copyright
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
WAIT_TIME = 4 # wait time between tasks
LABELING_METHOD="centroids method" # TODO: implement changing to not fancy
CLUSTER_AVG_IS_CENTROID=True
KEEP_WORD_REPS=False

rerun_embedding=True
LABEL_CHECK = True
CENTROID_CHECK = True
COCLUSTER_CHECK = True
NORM_PLOT = False # (NBVD) display norm plot
MOVIE=False
ASPECT_RATIO=4 # 1/6 for w2v; 10 for full tfidf; 4 for partial
SHOW_IMAGES=True
NEW_ABS=False

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
            if len(sentence) > 300 and sentence not in unique_sentences:
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

def get_representatives (data, model, n_clusters, n_representatives=5, reverse=False, method='naive_sum_tfidf', kind=None) -> dict:
    cluster_representatives = {}

    # get relevant properties
    if kind == 'docs':
        labels = model.row_labels_
    elif kind == 'words':
        labels = model.column_labels_
    else:
        raise Exception("get_representatives: must specify 'kind'")
    original_data = model.__original_data if hasattr(model, "__original_data") else None
    vec = model.__vectorization if hasattr(model, "__vectorization") else None
    if hasattr(model, "centroids"):
        if kind == 'docs':
            centroids = model.centroids[0]
        elif kind == 'words':
            centroids = model.centroids[1]
        centroids_ = get_centroids_by_cluster(data, labels, n_clusters) if CLUSTER_AVG_IS_CENTROID else centroids
    if hasattr(model, "R"):
        R,C = model.R,model.C

    if method == 'naive_sum_tfidf':
        reverse = not reverse # small distance ~ big sum
        dists = np.sum(data, axis=1) # rows are docs unless data is transposed
        all_distances = dists.repeat(n_clusters).reshape((dists.shape[0], n_clusters))
    elif method == 'naive_norm_tfidf':
        squashed_centroids = np.sum(centroids_.T, axis=1) # squash centroids to just 1 number per cluster
        
        big = max(1000, np.sum(np.abs(data)))
        squashed_centroids[:] = big

        all_distances = np.zeros((data.shape[0], n_clusters))
        for i, r in enumerate(data):
            all_distances[i] = [norm(r-centroid_sum) for centroid_sum in squashed_centroids]
    elif method == 'centroid_dif': # DBG
        all_distances = np.zeros((data.shape[0], n_clusters))
        for i, r in enumerate(data):
            all_distances[i] = [norm(r-centroid_sum) for centroid_sum in centroids_.T]
        """ # faster difference i think
        c_shape = centroids_.shape
        data_extra = data.reshape(*data.shape, 1).repeat(c_shape[1], axis=2) # add extra dim for clusters
        c_extra = centroids_.T.reshape(c_shape[1], c_shape[0], 1).repeat(data.shape[0], axis=2).T # add extra dim for number of samples
        all_distances = norm(data_extra-c_extra, axis=1)
        """
    elif method == 'naive_sum_tf': # DBG
        reverse = not reverse # small distance ~ big sum
        cv = CountVectorizer(vocabulary=vec.vocabulary_, **vec_kwargs)
        doc_w_counts = cv.fit_transform(original_data).toarray()
        
        if kind == 'docs':
            total_words_per_doc = np.sum(doc_w_counts, axis=1)
            dists = total_words_per_doc
        elif kind == 'words':
            total_docs_per_word = np.sum(doc_w_counts, axis=0)
            dists = total_docs_per_word
        all_distances = dists.repeat(n_clusters).reshape((dists.shape[0], n_clusters))
    elif method == 'matrix_assoc':
        reverse = not reverse # small distance ~ big assoc
        if kind == 'docs':
            all_distances = R
        elif kind == 'words':
            all_distances = C.T

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

def cluster_summary (data, model, n_doc_reps=5, n_word_reps=20, n_frequent=50, word_reps=None, verbose=True, logger=None):
    """Most representative documents/words are chosen based on distance to the (squashed) average of the assigned cluster.
    w_occurrence_per_d_cluster is a dict with length equal to n_word_reps*n_col_clusters and values corresponding to a dict of Bunch
    of the form 
        (occ = (occurence in top documents for d_cluster, occurence in bottom documents for d_cluster),
        assigned_dc = associated document cluster, 
        assigned_wc = associated word cluster, .
    (If d_cluster != cocluster-associated document cluster, no occurrence in bottom documents.)
    Note: if word_reps is given, word representatives are not calculated.

    Returns: ((most representative documents, most representative words), word occurrence per document cluster)"""

    print_or_log = logger.info if logger else (print if verbose else lambda s : None)
    has_cocluster_info = hasattr(model, "cluster_assoc")
    row_centroids, col_centroids = model.centroids
    row_labels_, column_labels_ = model.row_labels_, model.column_labels_
    vec, original_data = model.__vectorization, model.__original_data
    m, k = row_centroids.shape
    n, l = col_centroids.shape
    smallest_rcluster_size = min(np.bincount(row_labels_))
    if smallest_rcluster_size == 0:
        warnings.warn("A document cluster has size 0..", RuntimeWarning, stacklevel=2)

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
    
    #"""# DBG
    N_REPS_COMPARE=10
    row_cluster_representatives1 = get_representatives(data, model, k, n_representatives=N_REPS_COMPARE, method='naive_sum_tfidf', kind='docs')
    col_cluster_representatives1 = get_representatives(data.T, model, l, n_representatives=N_REPS_COMPARE, method='naive_sum_tfidf', kind='words')
    row_cluster_representatives2 = get_representatives(data, model, k, n_representatives=N_REPS_COMPARE, method='centroid_dif', kind='docs')
    col_cluster_representatives2 = get_representatives(data.T, model, l, n_representatives=N_REPS_COMPARE, method='centroid_dif', kind='words')
    row_cluster_representatives3 = get_representatives(data, model, k, n_representatives=N_REPS_COMPARE, method='matrix_assoc', kind='docs')
    col_cluster_representatives3 = get_representatives(data.T, model, l, n_representatives=N_REPS_COMPARE, method='matrix_assoc', kind='words')
    """
    print("docs:")
    print(*[f"{t[0]}\n{t[1]}" for t in zip(row_cluster_representatives.items(), row_cluster_representatives2.items())], sep="\n")
    print("comum:", *[set(r1).intersection(set(r2)) for r1,r2 in zip(row_cluster_representatives1.values(), row_cluster_representatives2.values())], sep="\n")
    print("\nwords:")
    print(*[f"{t[0]}\n{t[1]}" for t in zip(col_cluster_representatives.items(), col_cluster_representatives2.items())], sep="\n")
    print("comum:", *[set(c1).intersection(set(c2)) for c1,c2 in zip(col_cluster_representatives1.values(), col_cluster_representatives2.values())], sep="\n")
    """
    
    # get row- and column-cluster representatives
    row_cluster_representatives = get_representatives(data, model, k, n_representatives=n_doc_reps, kind='docs')
    if word_reps is None: # calculate word representatives if they are not given
        col_cluster_representatives = get_representatives(data.T, model, l, n_representatives=n_word_reps, kind='words')
    else:
        col_cluster_representatives = word_reps[:n_word_reps]
    
    # documents
    print_or_log("DOCUMENTS:\n")
    for i, reps in sorted(row_cluster_representatives.items()):
        print_or_log("cluster:", i)
        for rep in reps:
            print_or_log(f"rep: {rep}")
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
            print_or_log(",".join(to_print))
            print_or_log("--------------------------------------------------------\n")
        
        if has_cocluster_info:
            # cocluster analysis
            print_or_log("COCLUSTERS:")
            N = n_frequent
            if smallest_rcluster_size < N and smallest_rcluster_size > 0:
                N = smallest_rcluster_size
            # TODO: do top 10% / 20% / 25% instead?
            # TODO: account for clusters smaller than N; duct tape solution is to reduce N manually
            print_or_log(f"word (occurrence in top {N} documents)(occurrence in bottom {N} documents) (occurrence in other doc clusters)")
            row_reps_topN = get_representatives(data, model, 
                k, n_representatives=N, kind='docs')
            row_reps_bottomN = get_representatives(data, model, 
                k, n_representatives=N, reverse=True, kind='docs')
            
            # for each cocluster
            w_occurrence_per_d_cluster = OrderedDict() # store occurrence and dc info for each word
            for dc, wc in relevant_coclusters:
                print_or_log("cocluster:", (dc, wc),"\n")
                to_print = []
                reps = col_cluster_representatives[wc] # get the representatives for the word cluster

                # for each word, calculate its occurrence in each document cluster
                for w in reps:
                    if dc not in row_reps_topN:
                        warnigs.warn(f"## @#@ #@ {dc} not in row_reps!!!\n", UserWarning, stacklevel=2)
                        continue
                    else:
                        # occurrence for the dc in the cocluster
                        word = idx_to_word[w]
                        oc_top = 100/N * calculate_occurrence(word, original_data, row_reps_topN[dc])
                        oc_bottom = 100/N * calculate_occurrence(word, original_data, row_reps_bottomN[dc])
                        
                        w_occurrence_per_d_cluster[word] = OrderedDict()
                        w_occurrence_per_d_cluster[word][dc] = Bunch(occ=(oc_top, oc_bottom), assigned_dc=dc, assigned_wc=wc)

                        # occurrence for other dcs
                        oc_others = []
                        for rclust in sorted(row_reps_topN.keys()):
                            if rclust == dc:
                                continue
                            oc_other = 100/N * calculate_occurrence(word, original_data, row_reps_topN[rclust])
                            oc_others.append((rclust, oc_other))
                            w_occurrence_per_d_cluster[word][rclust] = Bunch(occ=(oc_other, ), assigned_dc=dc, assigned_wc=wc)

                        # print (later) word occurrence in each cluster
                        oc_other_str = "".join([f"({rclust}:{oc_other:.0f}%)" for rclust,oc_other in oc_others])
                        to_print.append(f"{word}(T:{oc_top:.0f}%)(B:{oc_bottom:.0f}%) {oc_other_str}")
                print_or_log(", ".join(to_print)+"\n--------------------------------------------------------\n")
    
    # visually compare different representative selection methods
    if SHOW_IMAGES:
        def __reps_dict_to_reps_list_and_labels (reps_dict, data, n_clusters):
            n_dim = data.shape[1]
            reps_matrix, reps_labels = np.zeros((n_clusters*N_REPS_COMPARE, n_dim), dtype=np.float64), np.zeros((n_clusters*N_REPS_COMPARE,), dtype=np.int64)
            total_count = 0
            for label, reps in reps_dict.items():
                n = len(reps)
                reps_matrix[total_count : total_count+n, :] = data[reps, :]
                reps_labels[total_count : total_count+n] = label
                total_count += n
            return reps_matrix, reps_labels
        r_clust_avg, c_clust_avg = get_centroids_by_cluster(data, row_labels_, k), get_centroids_by_cluster(data.T, column_labels_, l)
        # rows
        reps_list1, reps_labels1 = __reps_dict_to_reps_list_and_labels(row_cluster_representatives1, data, k)
        reps_list2, reps_labels2 = __reps_dict_to_reps_list_and_labels(row_cluster_representatives2, data, k)
        reps_list3, reps_labels3 = __reps_dict_to_reps_list_and_labels(row_cluster_representatives3, data, k)
        pca, pal = model.row_pca, model.row_c_palette

        def __cluster_means (thing, labels):
            n_labels = 1+max(labels)
            n_dim = thing.shape[1]
            means = np.zeros((n_labels,n_dim))
            for i in range(n_labels):
                means[i,:] = np.mean(thing[labels == i], axis=0)
            return means
        # calculate a metric
        means1 = __cluster_means(reps_list1, reps_labels1)
        means2 = __cluster_means(reps_list2, reps_labels2)
        means3 = __cluster_means(reps_list3, reps_labels3)
        print("norms:")
        print("12:", norm(means1-means2,axis=1))
        print("23:", norm(means2-means3,axis=1))
        print("13:", norm(means1-means3,axis=1))

        # apply dimensionality reduction (docs are already normalized)
        reps_list1_rdx, reps_list2_rdx, reps_list3_rdx = pca.transform(reps_list1), pca.transform(reps_list2), pca.transform(reps_list3),
        
        csize, size2, size3 = 50, 190, 550
        # plot representatives for different methods
        _, _, ax = centroid_scatter_plot(reps_list1, r_clust_avg, reps_labels1, pca=pca, palette=pal, centroid_size=csize, title="Row representative comparison")
        for i, point in enumerate(reps_list2_rdx):
            ax.scatter(*point, color=pal[reps_labels2[i]], marker="*", s=size2, alpha=0.7)
        for i, point in enumerate(reps_list3_rdx):
            ax.scatter(*point, color=pal[reps_labels3[i]], marker="+", s=size3, alpha=0.58) 

        handles = [mlines.Line2D([], [], color='black', marker='s', linestyle='None', markersize=16),
                    mlines.Line2D([], [], color='black', marker='o', linestyle='None', markersize=16),
                    mlines.Line2D([], [], color='black', marker='*', linestyle='None', markersize=20),
                    mlines.Line2D([], [], color='black', marker='+', linestyle='None', markersize=20)]
        labels = ['Cluster\naverages', '1:TF-IDF\nsum', '2:Centroid\ndifference', '3:R and C\nmatrices']
        ax.legend(handles, labels, bbox_to_anchor=(0.99,0.1), loc="lower left")

        # columns
        reps_list1, reps_labels1 = __reps_dict_to_reps_list_and_labels(col_cluster_representatives1, data.T, l)
        reps_list2, reps_labels2 = __reps_dict_to_reps_list_and_labels(col_cluster_representatives2, data.T, l)
        reps_list3, reps_labels3 = __reps_dict_to_reps_list_and_labels(col_cluster_representatives3, data.T, l)
        pca, pal = model.col_pca, model.col_c_palette

        # calculate a metric
        means1 = __cluster_means(reps_list1, reps_labels1)
        means2 = __cluster_means(reps_list2, reps_labels2)
        means3 = __cluster_means(reps_list3, reps_labels3)
        print("norms:")
        print("12:", norm(means1-means2,axis=1))
        print("23:", norm(means2-means3,axis=1))
        print("13:", norm(means1-means3,axis=1))

        # apply dimensionality reduction (docs are already normalized)
        reps_list1_rdx, reps_list2_rdx, reps_list3_rdx = pca.transform(reps_list1), pca.transform(reps_list2), pca.transform(reps_list3),

        # plot representatives for different methods
        _, _, ax = centroid_scatter_plot(reps_list1, c_clust_avg, reps_labels1, pca=pca, palette=pal, centroid_size=csize, title="Column representative comparison")
        for i, point in enumerate(reps_list2_rdx):
            ax.scatter(*point, color=pal[reps_labels2[i]], marker="*", s=size2, alpha=0.7)
        for i, point in enumerate(reps_list3_rdx):
            ax.scatter(*point, color=pal[reps_labels3[i]], marker="+", s=size3, alpha=0.58) 

        handles = [mlines.Line2D([], [], color='black', marker='s', linestyle='None', markersize=16),
                    mlines.Line2D([], [], color='black', marker='o', linestyle='None', markersize=16),
                    mlines.Line2D([], [], color='black', marker='*', linestyle='None', markersize=20),
                    mlines.Line2D([], [], color='black', marker='+', linestyle='None', markersize=20)]
        labels = ['Cluster\naverages', '1:TF-IDF\nsum', '2:Centroid\ndifference', '3:R and C\nmatrices']
        ax.legend(handles, labels, bbox_to_anchor=(0.99,0.1), loc="lower left")
        plt.show() 

    return (row_cluster_representatives, col_cluster_representatives), w_occurrence_per_d_cluster

def cocluster_words_bar_plot (w_occurrence_per_d_cluster, n_word_reps):
    n_hplots, n_vplots = math.ceil(math.sqrt(n_word_reps)), round(math.sqrt(n_word_reps)) # more rows than columns
    # DBG # im pretty sure this is correct for all reasonable numbers
    if n_hplots * n_vplots < n_word_reps:
        raise Exception("cocluster_words_bar_plot: math?")
    
    # translate w_occurrence_per_d_cluster into bar plots
    current_dc, current_ax = None, 1
    fig = plt.figure(figsize=(2*6.4,2*4.8))
    fig.set_tight_layout(True)
    for word, info in w_occurrence_per_d_cluster.items():
        w_assigned_dc = info[0].assigned_dc # assigned_dc for w, inside info for cluster 0
        if current_dc is None: 
            current_dc = w_assigned_dc # for initial item
            fig.suptitle(f"Word cluster {info[0].assigned_wc} (top {n_word_reps}): occurrence in doc clusters\n")

        # make a new figure for a different cluster
        if w_assigned_dc != current_dc:
            current_dc = w_assigned_dc
            current_ax = 1
            fig = plt.figure(figsize=(2*6.4,2*4.8))
            fig.suptitle(f"Word cluster {info[0].assigned_wc} (top {n_word_reps}): occurrence in doc clusters\n")
            fig.set_tight_layout(True)
        
        # bar plot for current word
        ax = fig.add_subplot(n_hplots, n_vplots, current_ax) # subplot index is 1-based
        current_ax += 1
        short_info = sorted([(k, v.occ[0]) for k,v in info.items()]) # value = occurrence in top docs
        labels, values = zip(*short_info) # split into keys, values
        color = ["#64001E" if (l != w_assigned_dc) else "#00FA8C" for l in labels]
        ax.bar(labels, values, color=color) # categorical plot
        ax.set_title(word)
    plt.show()

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

def kmeans_cluster_assoc (model, original_data, vec, vec_kwargs, row_labels, col_labels, DBG=False):
    print_or_nothing = print if DBG else lambda *args : None
    docs = np.array(original_data)
    print_or_nothing("km", docs.shape)
    words = np.array(vec.get_feature_names())
    k, l = model.n_row_clusters, model.n_col_clusters
    cluster_assoc = np.zeros((k,l))

    # select clusters and associate
    for dc in range(k):
        selected_docs_idx = (row_labels == dc)
        selected_docs = docs[selected_docs_idx]

        for wc in range(l):
            print_or_nothing(dc,wc,":")
            cv = CountVectorizer(vocabulary=vec.vocabulary_, **vec_kwargs)
            counts = np.mean(cv.fit_transform(selected_docs).toarray(),axis=0) # sum?
            print_or_nothing("counts",counts.shape)
            in_cluster_word_counts = counts[(col_labels == wc)]
            print_or_nothing("in cl", in_cluster_word_counts.shape)
            cluster_assoc[dc, wc] = np.sum(in_cluster_word_counts)
        print_or_nothing("row:", cluster_assoc[dc,:])
        cluster_assoc_row = cluster_assoc[dc,:]
        max_mask = (np.arange(l) == np.argmax(cluster_assoc_row))
        cluster_assoc_row[~max_mask] = 0
        print_or_nothing("row:", cluster_assoc[dc,:])
    cluster_assoc = np.array(cluster_assoc, dtype=bool)
    print_or_nothing(cluster_assoc)
    #sys.exit(0)
    return cluster_assoc

def kmeans_fix_labels (labels, RNG, probability=0.5):
    print("before:",np.bincount(labels))
    i_problem = np.argmax(np.bincount(labels))
    RNG = RNG or np.random.default_rng()
    selected_labels = labels[labels == i_problem]
    flat_length = selected_labels.shape[0]
    n_labels = 1+np.amax(labels)
    new_labels = labels.copy()

    # replace random i_problem labels with other labels
    np.place(new_labels, 
        new_labels == i_problem, 
        np.mod(selected_labels + (RNG.random(size=(flat_length,)) < probability) * RNG.integers(1, n_labels, size=(flat_length,), dtype=np.int32),
            n_labels, dtype=np.int32)
    )
    
    print("after:",np.bincount(new_labels))
    return new_labels

def do_task_single (data, original_data, vectorization, only_one=True, alg=ALG, 
        show_images=True, first_image_save_path=None, RNG_SEED=None, logger=None, iter_max=2000):
    RNG = np.random.default_rng(RNG_SEED)

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
        model = NBVD_coclustering(data, n_row_clusters=N_ROW_CLUSTERS, 
            n_col_clusters=N_COL_CLUSTERS, n_attempts=1, iter_max=iter_max, random_state=RNG_SEED, 
            verbose=False, save_history=MOVIE, save_norm_history=NORM_PLOT, logger=logger)
    elif alg == 'wbkm':
        model = wbkm.WBKM_coclustering(data, n_clusters=N_ROW_CLUSTERS, n_attempts=1,
            random_state=RNG_SEED, verbose=True, logger=logger)
    elif alg == 'spectralco':
        model = SpectralCoclustering(n_clusters=N_ROW_CLUSTERS, random_state=RNG_SEED)
        model.fit(data)

    # add extra info to model
    model.__original_data = original_data
    model.__vectorization = vectorization
    
    """ # clumps most docs into 1 cluster
    elif alg == 'kmeans':
        model = FooClass()
        model.data, model.n_row_clusters, model.n_col_clusters = data, N_ROW_CLUSTERS, N_COL_CLUSTERS
        
        model.kmeansR = KMeans(n_clusters=N_ROW_CLUSTERS, init='k-means++', random_state=RNG_SEED, n_init=10, tol=1e-6)
        model.kmeansR.fit(data)
        model.row_labels_ = np.array(model.kmeansR.labels_)
        model.kmeansC = KMeans(n_clusters=N_COL_CLUSTERS, init='k-means++', random_state=RNG_SEED, n_init=10, tol=1e-6)
        model.kmeansC.fit(data.T)
        print("r_iter, c_iter:", model.kmeansR.n_iter_, model.kmeansC.n_iter_)
        print("row labels", np.bincount(model.row_labels_), "\n")
        model.column_labels_ = kmeans_fix_labels(np.array(model.kmeansC.labels_), RNG=RNG)
        print("col labels", np.bincount(model.column_labels_))
        model.centroids = (model.kmeansR.cluster_centers_.T, model.kmeansC.cluster_centers_.T)
        model.cluster_assoc = kmeans_cluster_assoc(model, original_data, vectorization, vec_kwargs, model.row_labels_, model.column_labels_)
    """

    # show animation of clustering process
    if MOVIE and alg == 'nbvd':
        pyqtgraph_thing(data, model, 25)

    #########################
    # evaluate results 
    #########################

    ### internal indices
    # print silhouette scores
    silhouette = print_silhouette_score(data, model.row_labels_, model.column_labels_, logger=logger)

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

    # textual analysis
    representatives, w_occurrence_per_d_cluster = cluster_summary(data, model, logger=None)

    if show_images:
        cocluster_words_bar_plot(w_occurrence_per_d_cluster, n_word_reps=20)

    # return general statistics
    if alg == 'nbvd':
        bunch = Bunch(silhouette=MeanTuple(*silhouette), 
            best_iter=model.best_iter, best_norm=model.best_norm, n_attempts=1)
    elif alg == 'wbkm':
        bunch = Bunch(silhouette=MeanTuple(*silhouette), 
            max_iter_reached=model.best_max_iter_reached, best_norm=model.best_norm,
            no_zero_cols=model.best_no_zero_cols, n_attempts=1)
    else:
        bunch = Bunch(silhouette=MeanTuple(*silhouette), n_attempts=1)
    return (model, bunch)

def load_new_new_abstracts (path, n_abstracts, old_abstracts):
    old_abstracts_S = set(old_abstracts)
    df = pd.read_csv(path, delimiter=',')
    new_new_abstracts = df['abstract'][:n_abstracts].to_list()
    new_new_not_repeat = [ab for ab in new_new_abstracts if ab not in old_abstracts_S]
    new_processed_abstracts = Preprocessor().transform(new_new_not_repeat) # preprocess and eliminate duplicates
    print(f"\nnew abstracts: {len(new_processed_abstracts)} | old abstracts present: {len(new_new_abstracts) - len(new_new_not_repeat)}")
    return new_processed_abstracts, df

def vec_and_class_new_abstracts (extra_abstracts : Iterable, vec, model, logger=None, verbose=False):
    print_or_log = logger.info if logger else print
    row_centroids, col_centroids = model.centroids
    m, k = row_centroids.shape
    n, l = col_centroids.shape

    # vectorize abstracts
    Z = vec.transform(extra_abstracts).toarray()
    n, _ = Z.shape

    # classify rows and columns
    row_classification = NBVD_coclustering.get_labels(Z, row_centroids, k, m, n)
    col_classification = model.column_labels_
    return (Z, row_classification, col_classification)

def new_abs_reduced_centroids_plot (model, Z, new_abs_classification, new_centroids, RNG=None):
    RNG = RNG or np.default_rng()
    # calculate reduced centroids
    row_centroids = model.centroids[0]
    print(f"DBG: Z:{Z.shape} labels: {new_abs_classification.shape} centroids: {row_centroids.shape}")
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

def new_abs_cluster_summary_bar_plot (data, original_data, row_col_labels, row_col_centroids, cluster_assoc, vectorization, bar_plot=True, n_word_reps=20, use_orig_word_reps=False, logger=None):
    model = FooClass()
    model.row_labels_, model.column_labels_ = row_col_labels
    model.centroids = row_col_centroids
    model.cluster_assoc = cluster_assoc
    model.__vectorization, model.__original_data = vectorization, original_data
    if use_orig_word_reps:
        word_reps = get_representatives(data.T, model, l, n_representatives=n_word_reps, method='naive_sum_tfidf', kind='words')
    else:
        word_reps = None
    _, w_occurrence_per_d_cluster = cluster_summary(data, model, n_word_reps=n_word_reps, word_reps=word_reps, logger=logger)
    if bar_plot:
        cocluster_words_bar_plot(w_occurrence_per_d_cluster, n_word_reps=n_word_reps)


def misc_statistics (model, new_row_centroids, new_col_centroids, vec, new_new_abstracts):
    row_dist = norm(model.centroids[0] - new_row_centroids, axis=0) # frobenius norm
    print(f"Centroid difference for original and new abstracts:\n{row_dist}")
    orig_r_clust_avg = get_centroids_by_cluster(model.data, model.row_labels_, model.n_row_clusters)
    orig_c_clust_avg = get_centroids_by_cluster(model.data.T, model.column_labels_, model.n_col_clusters)
    row_dist = norm(orig_r_clust_avg - new_row_centroids, axis=0) # frobenius norm
    print(f"Centroid difference for original cluster avg and new abstracts:\n{row_dist}")
    print(f"norm for original centroids (r,c): {norm(model.centroids[0])}, {norm(model.centroids[1])}")
    print(f"mean for original centroids (r,c): {np.mean(model.centroids[0])}, {np.mean(model.centroids[1])}")

    # DBG
    s1 = set(vec.vocabulary_.keys())
    new_vec = TfidfVectorizer(**vec_kwargs)
    new_vec.fit(new_new_abstracts)
    s2 = set(new_vec.vocabulary_.keys())
    print("\n\nvocab1:", len(s1),"vocab2:", len(s2))
    print("diferenca vocab (2 nao em 1):",len(s2.difference(s1)))

def main():
    global RNG_SEED
    RNG, RNG_SEED = start_default_rng(seed=RNG_SEED)
    np.set_printoptions(edgeitems=5, threshold=sys.maxsize,linewidth=95) # very personal preferences :)
    os.makedirs('.embedding_cache', exist_ok=True)

    # read and process
    df = pd.read_csv('data/artigosUtilizados.csv', delimiter=',')
    abstracts = df['abstract']
    new_abstracts = Preprocessor().transform(abstracts)

    # do co-clustering
    # NOTE: docs are normalized (courtesy of sklearn); words arent
    data, vec = do_vectorization(new_abstracts, VECTORIZATION, **vec_kwargs)
    model, statistics = do_task_single(data, new_abstracts, vec, alg=ALG, iter_max=2000, RNG_SEED=RNG_SEED, show_images=SHOW_IMAGES)

    # analyze new abstracts
    if NEW_ABS:
        print("@@##@##@#@#@##@#@#@### #@# @##@ #@ ## @#@# #@ # @##@# @# @#@##@#@#@#@#","\t\tNEW ABSTRACTS\t\t","@@##@##@#@#@##@#@#@### #@# @##@ #@ ## @#@# #@ # @##@# @# @#@##@#@#@#@#", sep="\n")
        new_new_abstracts, df_new_abs = load_new_new_abstracts("data/artigosNaoUtilizados.csv", 496+20, abstracts)
        Z, new_abs_classification, _ = vec_and_class_new_abstracts(new_new_abstracts, vec, model, verbose=False)
        print_silhouette_score(Z, new_abs_classification, model.column_labels_)
        new_row_centroids = get_centroids_by_cluster(Z, new_abs_classification, model.n_row_clusters)
        new_abs_cluster_summary_bar_plot(Z, new_new_abstracts, (new_abs_classification, model.column_labels_), 
            (new_row_centroids, model.centroids[1]), model.cluster_assoc, vec, use_orig_word_reps=KEEP_WORD_REPS, bar_plot=SHOW_IMAGES, logger=None)
        
        # distance metrics and vocabulary sizes
        misc_statistics(model, new_row_centroids, model.centroids[1], vec, new_new_abstracts)

        # reduced-dimension scatter plot for new abstracts
        if SHOW_IMAGES:
            new_abs_reduced_centroids_plot(model, Z, new_abs_classification, new_row_centroids, RNG=RNG)

if __name__ == "__main__":
    main()