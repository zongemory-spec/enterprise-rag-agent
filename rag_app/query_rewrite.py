"""Small, inspectable domain dictionary. This is query rewriting, not model training."""
ALIASES = {'报账': '报销', '入司': '入职', '休假': '请假', '报销时限': '报销期限'}


def canonicalize(query):
    result=query
    for source,target in ALIASES.items():
        result=result.replace(source,target)
    return result
