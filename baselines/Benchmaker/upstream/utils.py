import re
import nltk
from nltk.util import ngrams
from nltk.translate.bleu_score import sentence_bleu
import numpy as np
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from collections import Counter
import math
nltk.download('punkt')

def calculate_shannon_entropy(strings_list):
    """
    Calculate the Shannon Entropy of a list of strings.

    Args:
        strings_list (list of str): A list of strings.

    Returns:
        float: The Shannon Entropy of the combined text from the list.
    """
    # Combine all strings into a single text
    combined_text = " ".join(strings_list)

    # Tokenize using NLTK's word tokenizer
    tokens = nltk.word_tokenize(combined_text)

    # Count frequencies of each unique token
    token_counts = Counter(tokens)

    # Calculate total number of tokens
    total_tokens = sum(token_counts.values())

    # Calculate Shannon Entropy
    entropy = -sum((count / total_tokens) * math.log2(count / total_tokens) for count in token_counts.values())

    return entropy,len(tokens)/len(strings_list)


def calculate_shannon_entropy_batch(strings_list_old,cands):

    # Combine all strings into a single text
    combined_text = " ".join(strings_list_old)

    # Tokenize using NLTK's word tokenizer
    tokens_old = nltk.word_tokenize(combined_text)
    entropy_max = -1
    cur_tem = 0
    for i in range(len(cands)):
        tem = cands[i]
        tokens_new = nltk.word_tokenize(tem)+tokens_old
        # Count frequencies of each unique token
        token_counts = Counter(tokens_new)
        # Calculate total number of tokens
        total_tokens = sum(token_counts.values())
        # Calculate Shannon Entropy
        entropy = -sum((count / total_tokens) * math.log2(count / total_tokens) for count in token_counts.values())
        if entropy > entropy_max:
            entropy_max = entropy
            cur_tem = i

    return cur_tem


def bleu2_matrix(strings):
    N = len(strings)
    bleu_matrix = np.zeros((N, N), dtype=np.float32)

    smoothing = SmoothingFunction().method1

    for i in range(N):
        ref_tokens = strings[i].split()
        for j in range(N):
            hyp_tokens = strings[j].split()

            if not ref_tokens or not hyp_tokens:
                bleu_matrix[i, j] = 0.0
            else:
                score = sentence_bleu(
                    [ref_tokens],
                    hyp_tokens,
                    weights=(0.5, 0.5, 0, 0),
                    smoothing_function=smoothing
                )
                bleu_matrix[i, j] = score

    return bleu_matrix



def preprocess(text):
    text = re.sub(r'[^\w\s]', '', text.lower())
    words = nltk.word_tokenize(text)
    return words


def count_ngrams(words, n=2):
    return list(ngrams(words, n))


def calculate_bleu(reference, candidate):
    return sentence_bleu([reference], candidate, weights=(0.5, 0.5))


def process_texts(ss):
    total_ngrams = []
    preprocessed_texts = [preprocess(s) for s in ss]

    for words in preprocessed_texts:
        ngram_list = count_ngrams(words)
        total_ngrams+=(ngram_list)

    return len(set(total_ngrams)), 0#avg_bleu

def mutual_bleu(s1,s2):

    preprocessed_texts1 = [preprocess(s) for s in s1]
    preprocessed_texts2 = [preprocess(s) for s in s2]

    bleu_scores = []
    for i in range(len(preprocessed_texts1)):
        for j in range(len(preprocessed_texts2)):
            bleu = calculate_bleu(preprocessed_texts1[i], preprocessed_texts2[j])
            bleu_scores.append(bleu)

    avg_bleu = sum(bleu_scores) / len(bleu_scores) if bleu_scores else 0

    return avg_bleu

import numpy as np
import matplotlib.pyplot as plt
from sklearn.manifold import TSNE

def t_sne(a,b,label1,label2):
    data = np.vstack((a, b))
    labels = np.array([0] * len(a) + [1] * len(b))

    tsne = TSNE(n_components=2, random_state=42)
    data_2d = tsne.fit_transform(data)

    indices = np.random.permutation(len(data_2d))
    data_2d = data_2d[indices]
    labels = labels[indices]

    plt.figure(figsize=(10, 8))
    plt.scatter(data_2d[labels == 0, 0], data_2d[labels == 0, 1], color='blue', label=label1,s=5)
    plt.scatter(data_2d[labels == 1, 0], data_2d[labels == 1, 1], color='red', label=label2,s=5)
    plt.legend()
    plt.xlabel('t-SNE Dimension 1')
    plt.ylabel('t-SNE Dimension 2')
    plt.title('t-SNE Visualization')
    plt.show()

from sklearn.metrics.pairwise import rbf_kernel

import numpy as np
from scipy.spatial.distance import cdist

def pairwise_euclidean_distance(embeddings):
    arr = np.array(embeddings)  # shape: (N, K)

    dist_matrix = cdist(arr, arr, metric='euclidean')
    return dist_matrix

def calculate_diversity(data):
    pairwise_distances = cdist(data, data, 'euclidean')
    avg_distance = np.sum(pairwise_distances) / (len(data) * (len(data) - 1))
    return avg_distance

def calculate_mmd(x, y, kernel='rbf', gamma=0.5):
    if kernel == 'rbf':
        xx = rbf_kernel(x, x, gamma=gamma)
        yy = rbf_kernel(y, y, gamma=gamma)
        xy = rbf_kernel(x, y, gamma=gamma)
        mmd = np.mean(xx) + np.mean(yy) - 2 * np.mean(xy)
    else:
        raise ValueError("Unsupported kernel type. Use 'rbf'.")
    return mmd