"""Explicit, idempotent schema setup. No seeding, acquisition or inference."""
from importlib import import_module


INITIALIZERS = (
    ('core', 'init_db'),
    ('pipeline', 'init'),
    ('watchlist', 'init'),
    ('local_translation', 'init'),
    ('showcase_history', 'init'),
    ('semantic_timeline', 'init'),
    ('article_pipeline', 'init'),
    ('question_titles', 'init'),
    ('question_search', 'init'),
    ('evidence_highlights', 'init'),
)


def main():
    for module, function in INITIALIZERS:
        getattr(import_module(module), function)()
        print('Schema ready: ' + module, flush=True)


if __name__ == '__main__':
    main()
