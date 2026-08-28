"""Evidence Library services (Section 6).

Kept as a subpackage rather than flat modules under app/services/ because the
tender side already owns modules of the same names — `chunking` and `progress`
in particular. Import these explicitly, e.g.

    from app.services.library import search, storage
    from app.services.library import library_progress as progress
"""
