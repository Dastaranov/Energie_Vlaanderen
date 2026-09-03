"""Ingest van overheidsheffingen die niet uit een VREG-werkboek komen.

`config/heffingen/` is handgeschreven masterdata. Voor de Vlaamse bijdrage
energiefonds bestaat er wél een publieke, jaarlijks bijgewerkte tabel; deze
module leest die uit zodat de controle niet met de hand hoeft.
"""
