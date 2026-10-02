"""dictgen: build entity dictionaries from public data (optional module).

Pipeline: collect → normalize names → diff against the existing plugin → judge
(approve / hold / review) → write plugin files → markdown report.

Sources implemented: ``ftc`` (Fair Trade Commission franchise brand list). The
Standard Korean Language Dictionary is used only as a runtime check (common
headwords are held back); its data is cached locally and never written to outputs.
"""
