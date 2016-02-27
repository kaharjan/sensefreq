#!/usr/bin/env python

import argparse, os, time
from collections import Counter
from itertools import islice

import numpy as np
import tensorflow as tf

UNK = '<UNK>'


def main():
    parser = argparse.ArgumentParser()
    arg = parser.add_argument
    arg('corpus')
    arg('--window', type=int, default=3)
    arg('--vocab-size', type=int, default=10000)
    arg('--vec-size', type=int, default=30)
    arg('--hidden-size', type=int, default=30)
    arg('--reload-vocab', action='store_true')
    arg('--nb-epoch', type=int, default=100)
    args = parser.parse_args()

    vocab_path = args.corpus + '.vocab.npz'
    if os.path.exists(vocab_path) and not args.reload_vocab:
        data = np.load(vocab_path)
        words, n_tokens, n_total_tokens = [data[k] for k in [
            'words', 'n_tokens', 'n_total_tokens']]
    else:
        words, n_tokens, n_total_tokens = \
            get_words(args.corpus, args.vocab_size)
        np.savez(vocab_path[:-len('.npz')],
                 words=words, n_tokens=n_tokens, n_total_tokens=n_total_tokens)
    print('{:,} tokens total, {:,} without <UNK>'.format(
        int(n_total_tokens), int(n_tokens)))
    model = Model(
        vec_size=args.vec_size,
        hidden_size=args.hidden_size,
        window=args.window,
        words=words)
    model.train(args.corpus, n_tokens=n_tokens, nb_epoch=args.nb_epoch)


def get_words(corpus, vocab_size):
    with open(corpus, 'r') as f:
        counts = Counter(w for line in f for w in tokenize(line))
    n_tokens = 0
    words = []
    for w, c in counts.most_common(vocab_size):
        words.append(w)
        n_tokens += c
    n_total_tokens = sum(counts.values())
    return np.array(words), n_tokens, n_total_tokens


def tokenize(line):
    # Text is already tokenized, so just split and lower
    return line.lower().split()


def get_word_to_idx(words):
    word_to_idx = {w: idx for idx, w in enumerate(words)}
    word_to_idx[UNK] = len(word_to_idx)
    return word_to_idx


class Model:
    def __init__(self, vec_size, hidden_size, window, words):
        self.window = window
        self.vec_size = vec_size
        self.word_to_idx = get_word_to_idx(words)
        self.batch_size = 32
        full_vocab_size = len(self.word_to_idx)
        input_size = self.window * 2

        embeddings = tf.Variable(tf.random_uniform(
            [full_vocab_size, self.vec_size], -1.0, 1.0))
        hidden_input_size = self.vec_size * input_size
        hidden_weights = tf.Variable(tf.random_uniform(
            [hidden_input_size, hidden_size], -0.01, 0.01))
        hidden_biases = tf.Variable(tf.zeros([hidden_size]))
        out_weights = tf.Variable(tf.truncated_normal(
            [full_vocab_size, hidden_size],
            stddev=1.0 / np.sqrt(self.vec_size)))
        out_biases = tf.Variable(tf.zeros([full_vocab_size]))

        self.inputs = tf.placeholder(tf.int32, shape=[None, input_size])
        self.labels = tf.placeholder(tf.int32, shape=[None, 1])

        embed = tf.nn.embedding_lookup(embeddings, self.inputs)
        embed = tf.reshape(embed, [-1, hidden_input_size])
        hidden = tf.nn.relu(tf.matmul(embed, hidden_weights) + hidden_biases)

        num_sampled = 512
        self.loss = tf.reduce_mean(tf.nn.nce_loss(
            out_weights, out_biases, hidden, self.labels,
            num_sampled, full_vocab_size))
        self.global_step = tf.Variable(0, name='global_step', trainable=False)
        self.train_op = tf.train.AdamOptimizer()\
            .minimize(self.loss, global_step=self.global_step)

    def train(self, corpus, n_tokens, nb_epoch):
        with tf.Session() as sess:
            sess.run(tf.initialize_all_variables())
            with open(corpus) as f:
                for n_epoch in range(1, nb_epoch + 1):
                    f.seek(0)
                    self.train_epoch(sess, self.batches(f), n_epoch, n_tokens)

    def train_epoch(self, sess, batches, n_epoch, n_tokens):
        batches_per_epoch = n_tokens / self.batch_size
        report_step = 1000
        t0 = epoch_start = time.time()
        losses = []
        for n_batch, (xs, ys) in enumerate(batches):
            _, loss_value = sess.run(
                [self.train_op, self.loss],
                feed_dict={self.inputs: xs, self.labels: ys})
            losses.append(loss_value)
            step = self.global_step.eval()
            if step % report_step == 0:
                progress = n_batch / batches_per_epoch
                t1 = time.time()
                speed = self.batch_size * report_step / (t1 - t0)
                print(
                    'Step {:,}; epoch {}; {:.1f}%: loss {:.3f} '
                    '(at {:.1f}K contexts/sec, {}s since epoch start)'
                    .format(
                        step, n_epoch, progress * 100, np.mean(losses),
                        speed / 1000, int(t1 - epoch_start)))
                losses = []
                t0 = t1

    def batches(self, f):
        unk_id = self.word_to_idx[UNK]
        read_lines_batch = 1000000
        while True:
            print('Reading next data batch...')
            word_ids = np.array([
                self.word_to_idx.get(w, unk_id)
                for line in islice(f, read_lines_batch)
                for w in tokenize(line)], dtype=np.int32)
            if len(word_ids) == 0:
                print('Batch empty.')
                break
            print('Vectorizing...')
            contexts = []
            for idx in range(self.window, len(word_ids) - self.window - 1):
                if word_ids[idx] != unk_id:
                    contexts.append(
                        word_ids[idx - self.window : idx + self.window + 1])
            contexts = np.array(contexts)
            np.random.shuffle(contexts)
            print('Batch ready.')
            for idx in range(0, len(contexts), self.batch_size):
                batch = contexts[idx : idx + self.batch_size]
                xs = np.delete(batch, self.window, 1)
                ys = batch[:,self.window : self.window + 1]
                yield xs, ys


if __name__ == '__main__':
    main()