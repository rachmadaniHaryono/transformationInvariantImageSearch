from itertools import zip_longest
import hashlib
import os
import pathlib
import shutil

from appdirs import user_data_dir
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from PIL import Image
import cv2
import tqdm

from .keypoints import compute_keypoints
from .phash import triangles_from_keypoints, hash_triangles, TRIANGLE_LOWER, TRIANGLE_UPPER


DB = SQLAlchemy()
DATA_DIR = user_data_dir('transformation_invariant_image_search', 'Tom Murphy')
pathlib.Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
DEFAULT_IMAGE_DIR = os.path.join(DATA_DIR, 'image')

checksum_phashes = DB.Table(
    'checksum_phashes',
    DB.Column('checksum_id', DB.Integer, DB.ForeignKey('checksum.id'), primary_key=True),
    DB.Column('phash_id', DB.Integer, DB.ForeignKey('phash.id'), primary_key=True))


class Base(DB.Model):
    __abstract__ = True
    id = DB.Column(DB.Integer, primary_key=True)


class Checksum(Base):
    value = DB.Column(DB.String(), unique=True, nullable=False)
    trash = DB.Column(DB.Boolean(), default=False)
    ext = DB.Column(DB.String(), nullable=False)
    phashes =  DB.relationship('Phash', secondary=checksum_phashes, lazy='subquery',
        backref=DB.backref('checksums', lazy=True))


    def __repr__(self):
        templ = '<Checksum(v={1}, ext={0.ext}, trash={0.trash})>'
        return templ.format(self, self.value[:7])

    def to_dict(self):
        keys = ['value', 'trash', 'ext', 'id']
        return {k: getattr(self, k) for k in keys}


class Phash(Base):
    value = DB.Column(DB.String(), unique=True, nullable=False)

    def __repr__(self):
        templ = '<Phash(v={0.value})>'
        return templ.format(self)


def get_or_create(session, model, **kwargs):
    """Creates an object or returns the object if exists."""
    instance = session.query(model).filter_by(**kwargs).first()
    created = False
    if not instance:
        instance = model(**kwargs)
        session.add(instance)
        created = True
    return instance, created


def get_image_path(checksum_value, ext, img_dir=DEFAULT_IMAGE_DIR):
    """Get image path.
    >>> import tempfile
    >>> image_fd = tempfile.mkdtemp()
    >>> get_image_path(
    ...     '54abb6e1eb59cccf61ae356aff7e491894c5ca606dfda4240d86743424c65faf',
    ...     'png', image_fd)
    '.../54/54abb6e1eb59cccf61ae356aff7e491894c5ca606dfda4240d86743424c65faf.png'
    """
    return os.path.join(img_dir, checksum_value[:2], '{}.{}'.format(checksum_value, ext))


def get_or_create_checksum_model(session, filename, img_dir=DEFAULT_IMAGE_DIR):
    """Get or create checksum model.
    >>> import tempfile
    >>> from . import main
    >>> filename = 'fullEndToEndDemo/inputImages/cat_original.png'
    >>> image_fd = tempfile.mkdtemp()
    >>> app = main.create_app(db_uri='sqlite://')
    >>> app.app_context().push()
    >>> DB.create_all()
    >>> _ = Checksum.query.delete()
    >>> get_or_create_checksum_model(DB.session, filename, image_fd)
    (<Checksum(v=54abb6e, ext=png, trash=False)>, True)
    >>> res = get_or_create_checksum_model(DB.session, filename, image_fd)
    >>> res
    (<Checksum(v=54abb6e, ext=png, trash=False)>, False)
    >>> m = res[0]
    >>> os.path.isfile(get_image_path(m.value, m.ext, image_fd))
    True
    """
    pil_img = Image.open(filename)
    sha256 = hashlib.sha256()
    with open(filename, 'rb') as f:
        for block in iter(lambda: f.read(128*1024), b''):
            sha256.update(block)
    sha256_csum = sha256.hexdigest()
    m, created = get_or_create(session, Checksum, value=sha256_csum)
    m.ext = pil_img.format.lower()
    m.trash = False
    dst_file = get_image_path(m.value, m.ext, img_dir)
    pathlib.Path(os.path.dirname(dst_file)).mkdir(parents=True, exist_ok=True)
    shutil.copy(filename, dst_file)
    return m, created


def grouper(iterable, n, fillvalue=None):
    """Collect data into fixed-length chunks or blocks.
    taken from:
    https://docs.python.org/3/library/itertools.html#itertools.zip_longest
    >>> list(grouper('ABCDEFG', 3, 'x'))
    [('A', 'B', 'C'), ('D', 'E', 'F'), ('G', 'x', 'x')]
    """
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)
