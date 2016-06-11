#!/usr/bin/env python
import argparse
from collections import Counter, defaultdict
import os.path
import pickle

from keras.models import Graph
from keras.layers.core import Dense, Dropout
from keras.layers.embeddings import Embedding
from keras.layers.recurrent import LSTM
import numpy as np


# FIXME - use real types
List = Iterator = Dict = defaultdict(int)
Any = None


def corpus_reader(corpus: str) -> Iterator[str]:
    """ Iterate over words in corpus.
    """
    # assume lemmatized and tokenized corpus
    with open(corpus) as f:
        for line in f:
            for word in line.strip().split():
                yield word


def get_features(corpus: str, *, n_features: int) -> (int, List[str]):
    cached_filename = '{}.f{}.pkl'.format(corpus, n_features)
    if os.path.exists(cached_filename):
        with open(cached_filename, 'rb') as f:
            return pickle.load(f)
    print('Getting words...', end=' ', flush=True)
    counts = Counter(corpus_reader(corpus))
    words = [w for w, _ in counts.most_common(n_features)]
    n_tokens = sum(counts.values())
    result = n_tokens, words
    with open(cached_filename, 'wb') as f:
        pickle.dump(result, f)
    print('done')
    return result


def data_gen(corpus, *, words: [str],
             n_features: int, window: int, batch_size: int)\
        -> Iterator[Dict[str, np.ndarray]]:
    # PAD = 0
    UNK = 1
    words = words[:n_features - 2]  # for UNK and PAD
    idx_to_word = {word: idx for idx, word in enumerate(words, 2)}

    def to_arr(contexts: List[(List[str], List[str], str)], idx: int)\
            -> np.ndarray:
        return np.array(
            [[idx_to_word.get(w, UNK) for w in context[idx]]
             for context in contexts],
            dtype=np.int32)

    buffer_max_size = 10000
    while True:
        buffer = []
        batch = []
        for word in corpus_reader(corpus):
            buffer.append(word)
            # TODO - add random padding?
            # TODO - some shuffling?
            if len(buffer) > 2 * window:
                left = buffer[-2 * window - 1 : -window - 1]
                output = buffer[-window - 1 : -window]
                right = buffer[-window:]
                batch.append((left, right, output))
            if len(batch) == batch_size:
                yield dict(
                    left=to_arr(batch, 0),
                    right=to_arr(batch, 1),
                    output=to_arr(batch, 2)[:,0],
                )
                batch[:] = []
            if len(buffer) > buffer_max_size:
                buffer[: -2 * window] = []


def build_model(*, n_features: int, embedding_size: int, hidden_size: int,
                window: int) -> Graph:
    print('Building model...', end=' ', flush=True)
    # TODO - use "non-legacy" way (?)
    model = Graph()
    model.add_input(name='left', input_shape=(window,), dtype='int')
    model.add_input(name='right', input_shape=(window,), dtype='int')
    embedding = Embedding(
        n_features, embedding_size, input_length=window, mask_zero=True)
    model.add_node(embedding, name='left_embedding', input='left')
    model.add_node(embedding, name='right_embedding', input='right')
    model.add_node(LSTM(hidden_size), name='forward', input='left_embedding')
    model.add_node(LSTM(hidden_size, go_backwards=True),
                   name='backward', input='right_embedding')
    model.add_node(Dropout(0.5), name='dropout', inputs=['forward', 'backward'])
    model.add_node(Dense(n_features, activation='softmax'),
                   name='softmax', input='dropout')
    model.add_output(name='output', input='softmax')
    model.compile(loss='sparse_categorical_crossentropy', optimizer='rmsprop')
    print('done')
    return model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('corpus')
    parser.add_argument('--n-features', type=int, default=10000)
    parser.add_argument('--embedding-size', type=int, default=128)
    parser.add_argument('--hidden-size', type=int, default=64)
    parser.add_argument('--window', type=int, default=10)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--n-epochs', type=int, default=1)
    parser.add_argument('--save')
    args = parser.parse_args()

    model = build_model(
        n_features=args.n_features,
        embedding_size=args.embedding_size,
        hidden_size=args.hidden_size,
        window=args.window)

    n_tokens, words = get_features(args.corpus, n_features=args.n_features)
    model.fit_generator(
        generator=data_gen(
            args.corpus,
            words=words,
            window=args.window,
            n_features=args.n_features,
            batch_size=args.batch_size),
        samples_per_epoch=n_tokens,
        nb_epoch=args.n_epochs)

    if args.save:
        model.save_weights(args.save, overwrite=True)


if __name__ == '__main__':
    main()