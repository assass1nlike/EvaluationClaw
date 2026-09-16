import re
import nltk
from nltk.util import ngrams
import numpy as np
from collections import Counter
import math
from scipy.spatial.distance import cdist
nltk.download('stopwords')

def calculate_shannon_entropy(strings_list):
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
    return {"Entropy":entropy,"AvgLen":len(tokens)/len(strings_list)}

def process_fai_response(sample):
    try:
        s = sample.split("Judgement:")
        analyses = s[0].strip("\n").strip(" ").strip("\n").strip(" ")
        s = s[1].split("Confidence:")
        judgement = s[0]
        matches = re.search(r"[012]", judgement)
        if matches:
            judgement = matches[0]
        else:
            return None
        confidence = s[1]
        matches = re.search(r"[012]", confidence)
        if matches:
            confidence = matches[0]
        else:
            return None
    except:
        # print(sample)
        return None
    return {
        'analyses':analyses,
        'judgement':judgement,
        'confidence':confidence
    }

def calculate_diversity(data):
    pairwise_distances = cdist(data, data, 'euclidean')
    avg_distance = np.sum(pairwise_distances) / (len(data) * (len(data) - 1))
    return avg_distance

def count_ngrams(words, n=2):
    return list(ngrams(words, n))

def preprocess(text):
    text = re.sub(r'[^\w\s]', '', text.lower())
    words = nltk.word_tokenize(text)
    return words

def process_texts(ss):
    total_ngrams = []
    preprocessed_texts = [preprocess(s) for s in ss]
    for words in preprocessed_texts:
        ngram_list = count_ngrams(words)
        total_ngrams+=(ngram_list)

    return len(set(total_ngrams))