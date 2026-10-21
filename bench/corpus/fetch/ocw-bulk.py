#!/usr/bin/env python3
"""Bulk sample MIT OpenCourseWare PDFs across departments.

usage: python3 -I ocw-bulk.py <n_courses> <per_course> <target_total> <seed>
Courses come from https://ocw.mit.edu/sitemap.xml, drawn round-robin over
departments (slug prefix before the first '-'). For each course, resources whose
slug starts with "mit" (course files, not video transcripts) are classified by
name (slides, notes, pset, exam, sol, written) and drawn round-robin over classes.
Each resource page's first .pdf link is fetched through fetch-one.sh into
incoming/mit-ocw/ as ocw2-<dept>-<class>__<basename>.pdf. One request per second.
"""
import os, random, re, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "pdfv-corpus/0.1 (personal PDF viewer test corpus; anders.bekkevard@gmail.com)"}
LIC = "CC BY-NC-SA 4.0 (MIT OpenCourseWare)"
CLASSES = [("written", r"written|hand|board|scan|ink"), ("slides", r"slide|ppt|pres|talk"),
           ("exam", r"exam|quiz|mid|final|test"), ("sol", r"sol"), ("pset", r"ps\d|pset|hw|assign|prob|_ps|homework|recit|_r\d"),
           ("notes", r"lec|note|ln|ch\d|chap|read")]

def get(url):
    time.sleep(1)
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")

def klass(slug):
    for name, rx in CLASSES:
        if re.search(rx, slug): return name
    return "other"

def main(n_courses, per_course, target, seed):
    rng = random.Random(seed)
    idx = get("https://ocw.mit.edu/sitemap.xml")
    courses = re.findall(r"https://ocw.mit.edu/courses/([^/<]+)/sitemap.xml", idx)
    by_dept = {}
    for c in courses: by_dept.setdefault(c.split("-")[0], []).append(c)
    for v in by_dept.values(): rng.shuffle(v)
    depts = sorted(by_dept, key=lambda d: -len(by_dept[d]))
    chosen = []
    while len(chosen) < n_courses and any(by_dept.values()):
        for d in depts:
            if by_dept[d] and len(chosen) < n_courses: chosen.append(by_dept[d].pop())
    done = 0
    for c in chosen:
        if done >= target: break
        try:
            sm = get(f"https://ocw.mit.edu/courses/{c}/sitemap.xml")
        except Exception as e:
            print("sitemap fail", c, e, file=sys.stderr); continue
        res = sorted(set(re.findall(rf"https://ocw.mit.edu/courses/{re.escape(c)}/resources/(mit[^/<]+)/", sm, re.I)))
        groups = {}
        for r in res: groups.setdefault(klass(r.lower()), []).append(r)
        for v in groups.values(): rng.shuffle(v)
        picks = []
        while len(picks) < per_course and any(groups.values()):
            for k in list(groups):
                if groups[k] and len(picks) < per_course: picks.append((k, groups[k].pop()))
        dept = c.split("-")[0]
        for k, r in picks:
            try:
                page = get(f"https://ocw.mit.edu/courses/{c}/resources/{r}/")
            except Exception as e:
                print("page fail", c, r, e, file=sys.stderr); continue
            m = re.search(r'href="([^"]+\.pdf)"', page)
            if not m: continue
            u = m.group(1)
            if u.startswith("/"): u = "https://ocw.mit.edu" + u
            base = re.sub(r"^[0-9a-f]{32}_", "", os.path.basename(u))
            p = subprocess.run([os.path.join(HERE, "fetch-one.sh"), "mit-ocw", u, f"ocw2-{dept}-{k}__{base}", f"{LIC}; course {c}", "80"],
                               env={**os.environ, "FETCH_SLEEP": "1"})
            done += p.returncode == 0
    print("done", done, file=sys.stderr)

if __name__ == "__main__":
    main(*map(int, sys.argv[1:5]))
