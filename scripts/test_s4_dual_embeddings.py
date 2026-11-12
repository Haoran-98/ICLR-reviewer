"""Check that vector caches cannot silently change paper order or accept invalid norms."""
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
from s4_dual_embeddings import checked_vectors, save_vectors


def check():
    with TemporaryDirectory() as directory:
        path = Path(directory)/'vectors.npz'
        vectors = np.zeros((2, 1024), dtype=np.float32)
        vectors[:, 0] = 1
        assert np.array_equal(save_vectors(path, vectors, 'sig', [1, 2], ['a', 'b']), vectors)
        for signature, ids in [('changed', [1, 2]), ('sig', [2, 1])]:
            try:
                checked_vectors(path, signature, ids)
            except ValueError:
                pass
            else:
                raise AssertionError('Mismatching checkpoint accepted')
        try:
            save_vectors(path, vectors*2, 'sig', [1, 2], ['a', 'b'])
        except ValueError:
            pass
        else:
            raise AssertionError('Non-unit vectors accepted')
    print('Embedding checkpoint signatures, paper order and unit norm checks passed.')


if __name__ == '__main__':
    check()
