"""Shared local deployment paths. Environment overrides work for CLI and Web jobs."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def configured(name, default):
    return Path(os.environ.get(name, default)).expanduser().resolve()


DATA = configured('ICLR_DATA_DIR', REPO/'.local-data')
RELEASE = configured('ICLR_RELEASE_DIR', DATA/'release')
CASES = configured('ICLR_CASES_DIR', DATA/'cases')
RUNS = configured('ICLR_REVIEW_RUNS', DATA/'runs')
SEED = configured('ICLR_REVIEW_SEED', CASES/'example')
ENTITY = configured('ICLR_ENTITY_ROOT', DATA/'entity')
PILOT = configured('ICLR_PILOT_DIR', DATA/'pilot')
DATABASE = configured('ICLR_DATABASE_HOME', DATA/'database')
CORPUS = configured('ICLR_REVIEWS_ROOT', DATA/'iclr_reviews')
DB_STATE = configured('ICLR_DATABASE_STATE', DATABASE/'state')
OPENREVIEW_TOKEN = configured('ICLR_OPENREVIEW_TOKEN_FILE', CORPUS/'fulltext/openreview.token')


def storage_path(relative):
    """Optional full-corpus experiments share one configurable storage root."""
    return configured('ICLR_STORAGE_ROOT', DATA/'research')/relative
