"""Workflow/consistency checks: run python -m unittest discover -s tests -v."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError

from poleq.api import create_app
from poleq import llm
from poleq.store import Problem, Store


class KnowledgeWorkflows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "library.sqlite3"
        self.store = Store(self.path)
        self.d = self.store.save("domains", {"name": "Matrices", "aliases": ["Linear algebra"]})
        self.d2 = self.store.save("domains", {"name": "Multivariate calculus"})
        self.c = self.store.save("concepts", {"name": "Skew-symmetric matrix", "aliases": ["SSM"], "definition": r"A square matrix $A$ with $A^{\mathsf{T}}=-A$.", "latex":r"A^{\mathsf{T}}=-A","domain_ids": [self.d["id"]]})
        self.c2 = self.store.save("concepts", {"name": "Determinant", "definition": "A scalar associated with a square matrix.", "latex":r"\det(A)=\sum_{\sigma\in S_n}\operatorname{sgn}(\sigma)\prod_{i=1}^{n}a_{i,\sigma(i)}","domain_ids": [self.d["id"], self.d2["id"]]})
        self.payload = {"title": "Odd-dimensional skew-symmetric determinant", "kind": "property", "body": "A real skew-symmetric matrix of odd order has zero determinant.", "latex": r"A^{\mathsf{T}}=-A,\quad n\text{ odd}\implies\det(A)=0", "concept_ids": [self.c["id"], self.c2["id"]]}

    def test_save_search_graph_edit_and_reopen(self):
        entry = self.store.save("entries", self.payload)
        for query in ["skew det", "SSM", "linear algebra", "calculus", "\\det(A)"]:
            result = self.store.search(query, entity="entries")
            self.assertEqual([x["record"]["id"] for x in result["items"]], [entry["id"]])
        self.assertEqual(self.store.search(entity="entries", concept_ids=[self.c["id"], self.c2["id"]], mode="all")["total"], 1)
        self.assertEqual(self.store.search(entity="entries", concept_ids=[str(uuid4())], mode="all")["total"], 0)
        graph = self.store.graph()
        edges = [x["data"] for x in graph["elements"] if "source" in x["data"]]
        self.assertEqual(len(edges), 1)
        self.assertEqual(set([edges[0]["source"], edges[0]["target"]]), {self.c["id"], self.c2["id"]})
        self.assertEqual(edges[0]["entry_ids"], [entry["id"]])
        self.assertTrue(any(x["data"].get("concept_ids") == [self.c2["id"]] for x in self.store.graph("domains")["elements"]))
        hierarchy_ids = {x["data"]["id"] for x in self.store.graph("hierarchy")["elements"] if "source" not in x["data"]}
        self.assertEqual(hierarchy_ids, {entry["id"], self.c["id"], self.c2["id"], self.d["id"], self.d2["id"]})
        edited = self.store.save("entries", {**self.payload, "concept_ids": [self.c["id"]]}, entry["id"])
        self.assertEqual(edited["created_at"], entry["created_at"])
        self.assertFalse(any("source" in x["data"] for x in self.store.graph()["elements"]))
        self.assertEqual(Store(self.path).get("entries", entry["id"]), edited)
        self.assertTrue(self.store.graph(limit=1)["truncated"])

    def test_reject_invalid_and_redundant_records_atomically(self):
        self.store.save("entries", self.payload)
        baseline = self.store.export()
        cases = [
            ("entries", self.payload),
            ("entries", {**self.payload, "title": "Other", "latex": r"\frac{x}"}),
            ("entries", {**self.payload, "body": r"Bad $\unknownMacro$"}),
            ("entries", {**self.payload, "concept_ids": [str(uuid4())]}),
            ("entries", {**self.payload, "concept_ids": []}),
            ("entries", {**self.payload, "concept_ids": [self.c["id"]] * 2}),
            ("entries", {**self.payload, "extra": "ignored?"}),
            ("entries", {**self.payload, "title": self.payload["body"].upper().rstrip('.') + '!'}),
            ("domains", {"name": "  MATRICES "}),
            ("domains", {"name": "Another name", "aliases": ["Linear algebra"]}),
            ("concepts", {"name": " ssm ", "definition": "Duplicate", "latex":"x=1", "domain_ids": [self.d["id"]]}),
            ("concepts", {"name": "Broken", "definition": "Definition", "latex":"x=1", "domain_ids": [self.c["id"]]}),
            ("concepts", {"name": "Missing formula", "definition": "Definition", "domain_ids": [self.d["id"]]}),
            ("concepts", {"name": "Empty formula", "definition": "Definition", "latex":"", "domain_ids": [self.d["id"]]}),
            ("concepts", {"name": "Bad formula", "definition": "Definition", "latex":r"\frac{x}", "domain_ids": [self.d["id"]]}),
            ("concepts", {"name": "Wrapped formula", "definition": "Definition", "latex":"$x=1$", "domain_ids": [self.d["id"]]}),
        ]
        for entity, payload in cases:
            with self.subTest(entity=entity,payload=payload), self.assertRaises((Problem,ValidationError)):
                self.store.save(entity,payload)
            self.assertEqual(self.store.export(),baseline)
        with self.assertRaises(Problem):
            self.store.delete("concepts", self.c["id"])
        self.assertEqual(self.store.export(),baseline)

    def test_portable_restore_replacement_backup_and_invalid_archives(self):
        entry = self.store.save("entries", self.payload)
        exported = self.store.export()
        other = Store(Path(self.tmp.name) / "new" / "library.sqlite3")
        other.restore(json.loads(json.dumps(exported)))
        self.assertEqual(other.export(), exported)
        self.assertEqual(other.graph(), self.store.graph())
        self.assertTrue(other.restore(exported)["unchanged"])
        for mutate in [
            lambda a: a["entries"][0].update(concept_ids=[str(uuid4())]),
            lambda a: a["concepts"].append(copy.deepcopy(a["concepts"][0])),
            lambda a: a["domains"][0].update(created_at="bad-date"),
            lambda a: a.update(version=3),
            lambda a: a.pop("format"),
        ]:
            bad = copy.deepcopy(exported); mutate(bad)
            with self.assertRaises((Problem,ValidationError)):
                other.restore(bad,replace=True)
            self.assertEqual(other.export(),exported)
        self.store.delete("entries",entry["id"])
        backups = list((self.path.parent / "backups").glob("*.json"))
        self.assertTrue(any(json.loads(p.read_text()) == exported for p in backups))
        with self.assertRaises(Problem):
            self.store.restore(exported)
        self.store.restore(exported,replace=True)
        self.assertEqual(self.store.export(),exported)

    def test_agent_api_and_cli_share_contract(self):
        with TestClient(create_app(self.path)) as client:
            self.assertEqual(client.get("/api/catalog").status_code,200)
            self.assertEqual(len(client.get("/api/catalog").json()["concepts"]),2)
            self.assertEqual(client.get("/api/health").json()["counts"]["domains"],2)
            response = client.post("/api/entries",json=self.payload)
            self.assertEqual(response.status_code,201,response.text)
            record = response.json()
            self.assertEqual(client.post("/api/entries",json=self.payload).status_code,409)
            self.assertEqual(client.post("/api/entries",json={**self.payload,"extra":True}).status_code,422)
            self.assertEqual(client.post("/api/entries",json=self.payload,headers={"Origin":"https://example.com"}).status_code,403)
            self.assertEqual(client.get("/api/health",headers={"Host":"evil.example"}).status_code,400)
            self.assertEqual(client.post("/api/validate/entry",json=self.payload).json()["valid"],True)
            paths = client.get("/openapi.json").json()["paths"]
            self.assertIn("/api/entries/{record_id}",paths)
            self.assertEqual(client.get("/api/search",params={"q":"SSM","entity":"entries"}).json()["total"],1)
            self.assertEqual(client.get("/").status_code,200)
            self.assertEqual(client.get("/static/app.js").status_code,200)
            self.assertEqual(client.get("/api/entries/invalid-id").status_code,422)
            self.assertEqual(client.post("/api/import?replace=true",json={}).status_code,422)
            self.assertEqual(client.delete(f'/api/concepts/{self.c["id"]}').status_code,409)
        output = subprocess.run([sys.executable,"-m","poleq.cli","--db",str(self.path),"search","SSM","--entity","entries"],text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(output.stdout)["items"][0]["record"]["id"],record["id"])
        exported = Path(self.tmp.name) / "archive.json"
        subprocess.run([sys.executable,"-m","poleq.cli","--db",str(self.path),"export",str(exported)],capture_output=True,check=True)
        self.assertEqual(json.loads(exported.read_text()),self.store.export())

    def test_agent_error_codes_and_cli_validation(self):
        client = TestClient(create_app(self.path))
        self.assertEqual(client.get(f"/api/entries/{uuid4()}").json()["detail"]["code"],"not_found")
        self.assertEqual(client.get("/api/does-not-exist").json()["detail"]["code"],"not_found")
        entry = self.store.save("entries",self.payload)
        duplicate = client.post("/api/entries",json=self.payload)
        self.assertEqual(duplicate.status_code,409)
        self.assertEqual(duplicate.json()["detail"]["code"],"duplicate_entry")
        invalid = client.post("/api/entries",json={**self.payload,"extra":True})
        self.assertEqual(invalid.json()["detail"]["code"],"validation_error")
        repeated_title = client.post("/api/entries",json={**self.payload,"title":self.payload["body"]})
        self.assertEqual(repeated_title.status_code,422)
        self.assertEqual(repeated_title.json()["detail"]["code"],"validation_error")
        linked = client.delete(f'/api/concepts/{self.c["id"]}')
        self.assertEqual(linked.json()["detail"]["code"],"record_in_use")
        forbidden = client.post("/api/entries",json=self.payload,headers={"Origin":"https://example.com"})
        self.assertEqual(forbidden.json()["detail"]["code"],"forbidden")

        entry_file = Path(self.tmp.name) / "entry.json"
        entry_file.write_text(json.dumps(self.payload))
        failed = subprocess.run([sys.executable,"-m","poleq.cli","--db",str(self.path),"--compact","add","entries",str(entry_file)],text=True,capture_output=True)
        self.assertEqual(failed.returncode,1)
        self.assertEqual(json.loads(failed.stderr)["error"]["code"],"duplicate_entry")
        bad_args = subprocess.run([sys.executable,"-m","poleq.cli","--db",str(self.path),"not-a-command"],text=True,capture_output=True)
        self.assertEqual(bad_args.returncode,2)
        self.assertEqual(json.loads(bad_args.stderr)["error"]["code"],"invalid_arguments")

        concept_file = Path(self.tmp.name) / "concept.json"
        concept_file.write_text(json.dumps({k:self.c[k] for k in ("name","definition","latex","aliases","domain_ids")}))
        checked = subprocess.run([sys.executable,"-m","poleq.cli","--db",str(self.path),"--compact","validate","--entity","concepts",str(concept_file)],text=True,capture_output=True,check=True)
        output = json.loads(checked.stdout)
        self.assertTrue(output["valid"])
        self.assertEqual(output["entity"],"concepts")
        self.assertEqual(output["record"]["name"],self.c["name"])

        fetched = subprocess.run([sys.executable,"-m","poleq.cli","--db",str(self.path),"get","entries",entry["id"]],text=True,capture_output=True,check=True)
        editable = json.loads(fetched.stdout)
        editable["title"] = "Edited odd-order determinant"
        entry_file.write_text(json.dumps(editable))
        subprocess.run([sys.executable,"-m","poleq.cli","--db",str(self.path),"update","entries",entry["id"],str(entry_file)],text=True,capture_output=True,check=True)
        self.assertEqual(self.store.get("entries",entry["id"])["title"],"Edited odd-order determinant")

    def test_llm_drafts_validate_retry_and_never_save(self):
        baseline = self.store.export()
        calls = []
        def respond(request):
            data = json.loads(request.content); calls.append(data)
            self.assertFalse(data["think"])
            self.assertEqual(data["format"]["additionalProperties"],False)
            content = {key:self.payload[key] for key in ("title","body","latex")}
            if len(calls) == 1: content["latex"] = r"\invalid"
            return httpx.Response(200,json={"message":{"content":json.dumps(content)}})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            draft = llm.draft(self.store,{"text":"Odd SSM determinant zero","concept_ids":[self.c["id"]]},client)
        self.assertEqual(len(calls),2)
        self.assertTrue(draft["needs_review"])
        self.assertEqual(draft["entry"]["concept_ids"],[self.c["id"]])
        self.assertEqual(self.store.export(),baseline)
        with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(503))) as client:
            with self.assertRaises(Problem):
                llm.draft(self.store,{"text":"A property","concept_ids":[self.c["id"]]},client)
        self.assertEqual(self.store.export(),baseline)
        for opening,closing in [("$","$"),("$$","$$"),(r"\[",r"\]"),(r"\(",r"\)")]:
            content = {key:self.payload[key] for key in ("title","body","latex")}
            content["latex"] = opening + content["latex"] + closing
            with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={"message":{"content":json.dumps(content)}}))) as client:
                result=llm.draft(self.store,{"text":"A property","concept_ids":[self.c["id"]]},client)
                self.assertEqual(result["entry"]["latex"],self.payload["latex"])

    def test_last_opened_tracking_and_staleness_filters(self):
        entry = self.store.save("entries", self.payload)
        created = self.store.search(entity="entries")["items"][0]
        self.assertIsNotNone(created["last_opened_at"], "A new record counts as opened on creation")
        self.assertEqual(self.store.search(entity="entries", stale_days=45)["total"], 0)
        self.assertEqual(self.store.search(entity="entries", stale_days=15, stale_max_days=30)["total"], 0)

        def backdate(entity, record_id, days):
            self.store.mark_opened(entity, record_id, at=(datetime.now(timezone.utc) - timedelta(days=days)).isoformat())

        # One record per window plus a never-opened one; disjoint buckets must not overlap.
        backdate("entries", entry["id"], 20)
        recent = self.store.save("entries", {**self.payload, "title": "Synthetic recent", "body": "Synthetic recent body", "latex": r"x=1"})
        older = self.store.save("entries", {**self.payload, "title": "Synthetic older", "body": "Synthetic older body", "latex": r"x=2"})
        backdate("entries", recent["id"], 35)
        backdate("entries", older["id"], 50)
        never = self.store.save("entries", {**self.payload, "title": "Synthetic never", "body": "Synthetic never body", "latex": r"x=3"})
        with self.store.connection() as db:
            db.execute("DELETE FROM opened WHERE record_id=?", (never["id"],))
            db.commit()

        def ids(**filters):
            return [item["record"]["id"] for item in self.store.search(entity="entries", **filters)["items"]]

        self.assertEqual(ids(stale_days=15, stale_max_days=30), [entry["id"]])
        self.assertEqual(ids(stale_days=30, stale_max_days=45), [recent["id"]])
        self.assertEqual(ids(stale_days=45), [never["id"], older["id"]], "Never opened is infinitely stale and sorts first")
        self.assertEqual(ids(stale_days=15, stale_max_days=45), [recent["id"], entry["id"]], "Longest untouched first")
        self.assertEqual(ids(stale_max_days=30), [entry["id"]])
        with self.assertRaises(Problem):
            self.store.search(stale_days=30, stale_max_days=30)
        self.assertTrue(all(item["entity"] != "domains" for item in self.store.search(stale_days=45)["items"]), "Domains have no opening history")

        # Reopening moves a record out of its window without touching its edit timestamp.
        before = self.store.get("entries", entry["id"])["updated_at"]
        self.store.mark_opened("entries", entry["id"])
        self.assertEqual(ids(stale_days=15, stale_max_days=30), [])
        self.assertEqual(self.store.get("entries", entry["id"])["updated_at"], before)
        reopened = next(item for item in self.store.search(entity="entries")["items"] if item["record"]["id"] == entry["id"])
        self.assertEqual(reopened["last_opened_at"], self.store.opened_at("entries", entry["id"]))

        # Concepts track the same way; domains do not participate.
        backdate("concepts", self.c["id"], 40)
        self.assertEqual([item["record"]["name"] for item in self.store.search(entity="concepts", stale_days=30, stale_max_days=45)["items"]], ["Skew-symmetric matrix"])
        with self.assertRaises(Problem):
            self.store.mark_opened("domains", self.d["id"])
        with self.assertRaises(Problem):
            self.store.mark_opened("entries", str(uuid4()))

        with TestClient(create_app(self.path)) as client:
            opened = client.post(f'/api/entries/{entry["id"]}/opened')
            self.assertEqual(opened.status_code, 200)
            self.assertEqual(opened.json()["entity"], "entries")
            self.assertEqual(client.get(f'/api/entries/{entry["id"]}').json()["last_opened_at"], opened.json()["last_opened_at"])
            self.assertNotIn("last_opened_at", client.get(f'/api/domains/{self.d["id"]}').json())
            self.assertEqual(client.post(f'/api/domains/{self.d["id"]}/opened').status_code, 422)
            self.assertEqual(client.post(f'/api/entries/{uuid4()}/opened').status_code, 404)
            self.assertEqual(client.get("/api/search", params={"entity": "entries", "stale_days": 30, "stale_max_days": 45}).json()["total"], 1)

        output = subprocess.run([sys.executable, "-m", "poleq.cli", "--db", str(self.path), "search", "--entity", "entries", "--stale", "45"], text=True, capture_output=True, check=True)
        self.assertEqual({item["record"]["id"] for item in json.loads(output.stdout)["items"]}, {never["id"], older["id"]})
        output = subprocess.run([sys.executable, "-m", "poleq.cli", "--db", str(self.path), "opened", "entries", older["id"]], text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(output.stdout)["id"], older["id"])

    def test_five_thousand_entries_restore_search_and_pagination(self):
        archive = self.store.export()
        now = self.c["created_at"]
        archive["entries"] = [
            {**self.payload, "id":str(uuid4()), "created_at":now, "updated_at":now,
             "title":f"Synthetic property {i}", "body":f"Synthetic benchmark record {i}" + (" needle" if i == 4242 else ""),
             "latex":f"x_{{{i}}}={i}"}
            for i in range(5000)
        ]
        self.store.restore(archive,replace=True)
        self.assertEqual(self.store.search(entity="entries",limit=40)["total"],5000)
        self.assertEqual(len(self.store.search(entity="entries",limit=40,offset=4980)["items"]),20)
        result = self.store.search("needle",entity="entries")
        self.assertEqual(result["total"],1)
        self.assertEqual(result["items"][0]["record"]["title"],"Synthetic property 4242")
        self.assertEqual(len(self.store.export()["entries"]),5000)

    def test_generated_title_is_a_short_distinct_label(self):
        baseline = self.store.export()
        for bad_title in [self.payload["body"].upper().rstrip('.'), " ".join(["word"] * 11), "Odd SSM determinant zero"]:
            calls = []
            def respond(request):
                calls.append(json.loads(request.content))
                content = {key:self.payload[key] for key in ("title","body","latex")}
                if len(calls) == 1: content["title"] = bad_title
                return httpx.Response(200,json={"message":{"content":json.dumps(content)}})
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                result = llm.draft(self.store,{"text":"Odd SSM determinant zero","concept_ids":[self.c["id"]]},client)
            self.assertEqual(result["entry"]["title"],self.payload["title"])
            self.assertEqual(len(calls),2)
        content = {key:self.payload[key] for key in ("title","body","latex")}
        content["title"] = content["body"]
        with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={"message":{"content":json.dumps(content)}}))) as client:
            with self.assertRaises(Problem):
                llm.draft(self.store,{"text":"A property","concept_ids":[self.c["id"]]},client)
        self.assertEqual(self.store.export(),baseline)

    def test_concept_definition_drafts_are_validated_and_never_saved(self):
        baseline = self.store.export()
        calls = []
        request = {"name":"Orthogonal matrix","aliases":["Orthogonal"],"domain_ids":[self.d["id"]],"context":"Use real square matrices."}
        def respond(req):
            calls.append(json.loads(req.content))
            content = {"title":"Orthogonal matrix","body":"An orthogonal matrix is a real square matrix whose transpose equals its inverse.","latex":r"Q\in\mathbb{R}^{n\times n},\quad Q^{\mathsf{T}}Q=I_n"}
            if len(calls) == 1: content["latex"] = r"\notACommand"
            return httpx.Response(200,json={"message":{"content":json.dumps(content)}})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            result = llm.draft_concept(self.store,request,client)
            with self.assertRaises(Problem):
                llm.draft_concept(self.store,{**request,"domain_ids":[str(uuid4())]},client)
            with self.assertRaises(ValidationError):
                llm.draft_concept(self.store,{**request,"domain_ids":[self.d["id"]]*2},client)
        self.assertEqual(len(calls),2)
        self.assertIn('Matrices',calls[0]["messages"][1]["content"])
        self.assertIn(request["context"],calls[0]["messages"][1]["content"])
        self.assertEqual(result["concept"]["domain_ids"],request["domain_ids"])
        self.assertEqual(result["concept"]["aliases"],request["aliases"])
        self.assertNotIn('$$',result["concept"]["definition"])
        self.assertIn(r"Q^{\mathsf{T}}Q=I_n",result["concept"]["latex"])
        self.assertTrue(result["needs_review"])
        self.assertEqual(self.store.export(),baseline)
        with patch('poleq.api.llm.draft_concept',return_value=result), TestClient(create_app(self.path)) as api:
            self.assertEqual(api.post('/api/draft/concept',json=request).json(),result)
            self.assertEqual(api.post('/api/draft/concept',json={**request,"extra":True}).status_code,422)
            self.assertEqual(api.post('/api/draft/concept',json={**request,"domain_ids":[]}).status_code,422)
            self.assertIn('/api/draft/concept',api.get('/openapi.json').json()["paths"])
        self.assertEqual(self.store.export(),baseline)
        with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(503))) as client:
            with self.assertRaises(Problem): llm.draft_concept(self.store,request,client)
        self.assertEqual(self.store.export(),baseline)
        saved = self.store.save('concepts',result['concept'])
        self.assertEqual(Store(self.path).get('concepts',saved['id'])['latex'],result['concept']['latex'])
        restored = Store(Path(self.tmp.name) / 'restored.sqlite3')
        restored.restore(self.store.export())
        self.assertEqual(restored.export(),self.store.export())


if __name__ == "__main__":
    unittest.main()
