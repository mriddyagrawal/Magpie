import sys, os, json, random, io
SP = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, SP+"/pylibs")
import pyarrow.parquet as pq
SEED = 0; N = 500
t = pq.read_table(SP+"/data/Full/random-00000-of-00001.parquet")
rows = [{"id":t.column("id")[i].as_py(), "question_id":t.column("question_id")[i].as_py(),
         "question":t.column("question")[i].as_py(), "answer":t.column("answer")[i].as_py(),
         "image_source":t.column("image_source")[i].as_py(), "row":i} for i in range(t.num_rows)]
rnd = random.Random(SEED); idx = sorted(rnd.sample(range(len(rows)), N))
sub = [rows[i] for i in idx]
json.dump({"seed":SEED,"n":N,"split":"random","source":"lmms-lab/POPE Full/random",
           "items":sub}, open(SP+"/sample_500.json","w"), indent=1)
from collections import Counter
print("sampled:",len(sub),"answer balance:",Counter(r["answer"] for r in sub))
print("unique images:",len(set(r["image_source"] for r in sub)))
print("first 3:",[(r["id"],r["question"],r["answer"]) for r in sub[:3]])
