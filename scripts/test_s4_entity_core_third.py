"""Check exact one-third quotas, seed retention and dynamic progress totals without API calls."""
from pathlib import Path
from tempfile import TemporaryDirectory

from s4_entity_core_third import select_third
from s4_entity_core500 import Progress
from s4_reproduce500 import read, write


def check():
    population=[dict(paper_id=i,year=2024+(i//20),area='a' if i%2 else 'b') for i in range(61)]
    seeds={0,1,20,21,40,41}
    selected,quotas=select_third(population,seeds)
    assert len(selected)==21 and seeds<=set(selected)
    assert select_third(population,seeds)==(selected,quotas)
    for key,quota in quotas.items():
        n=sum((p['year'],p['area'])==key for p in population)
        assert quota in {n//3,(n+2)//3}
        assert sum(p['paper_id'] in selected and (p['year'],p['area'])==key for p in population)==quota
    with TemporaryDirectory() as directory:
        root=Path(directory);(root/'runtime').mkdir()
        write(root/'inputs.json',[dict(paper_id=i) for i in range(7)])
        progress=Progress(root);progress.save()
        saved=read(root/'progress.json')
        assert saved['papers']==7 and saved['embedding_total']==28
        assert '0/7' in (root/'PROGRESS.md').read_text()
        assert (root/'runtime/progress.log').exists()
    print('PASS: proportional one-third quotas, deterministic sampling, seed retention, dynamic totals and logs')


if __name__=='__main__':
    check()
