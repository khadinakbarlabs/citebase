"""Evidence-bound editorial contacts and single-use mail handoffs."""
import asyncio
import re
import uuid
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import fact_checks
import history
import storage
import tools
import work_actions
import work_outreach as outreach


class Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.names = []
        self.anchor = None
        self.hidden = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template"):
            self.hidden = True
        if self.hidden:
            return
        a = dict(attrs)
        if tag == "meta" and (a.get("name") or "").lower() == "author" and a.get("content"):
            self.names.append(a["content"][:160])
        if tag == "a":
            self.anchor = (a.get("href") or "", (a.get("rel") or "").lower().split(), [])

    def handle_data(self, data):
        if self.hidden:
            return
        if self.anchor:
            self.anchor[2].append(data)
        elif len(data) <= 320 and "@" in data:
            # Only short publisher contact lines with an explicit email label are evidence.
            if re.search(r"\b(?:e-?mail|contact|editorial|newsroom)\b", data, re.I):
                addresses = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", data)
                if len(addresses) == 1:
                    self.links.append(("mailto:" + addresses[0], [], data.strip()))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template"):
            self.hidden = False
        if tag == "a" and self.anchor:
            href, rel, chunks = self.anchor
            self.links.append((href, rel, " ".join("".join(chunks).split())[:160]))
            self.anchor = None


def verify_citation(project, term, url, imported=()):
    if url and any(r.get("term") == term and r.get("url") == url for r in imported):
        return
    ids = {q['prompt_id'] for q in project['panel'] if term in (q['prompt_id'], q['prompt'])}
    if not url or not any(r.get('prompt_id') in ids and url in fact_checks.safe_evidence_urls(r.get('cited_urls'), 60)
                          for r in project['runs']):
        raise ValueError("Select a saved question and its exact cited article.")


def inspect_article(url):
    sa = tools.sa
    origin = urlsplit(url).netloc
    robots = sa.fetch(urljoin(url, '/robots.txt'))
    policy = RobotFileParser()
    if robots['status'] == 200 and not robots.get('truncated'):
        policy.parse(sa.decode(robots['body'], robots['headers']).splitlines())
    elif robots['status'] in (404, 410):
        policy.parse([])
    else:
        raise ValueError("The publisher's crawl permissions could not be verified.")
    def page(address):
        if not policy.can_fetch(sa.UA, address):
            return None
        reply = sa.fetch(address)
        if reply['status'] != 200 or 'html' not in reply['headers'].get('content-type', 'text/html').lower():
            return None
        parser = Article()
        parser.feed(sa.decode(reply['body'], reply['headers']))
        return parser

    article = page(url)
    if not article:
        raise ValueError("The cited article could not be inspected.")
    authors = list(article.names)
    profiles = {}
    for href, rel, name in article.links:
        if 'author' in rel and name:
            authors.append(name)
            target = urljoin(url, href)
            try:
                if href and target != url and urlsplit(target).netloc == origin and fact_checks.clean_source(target):
                    profiles.setdefault(target, set()).add(name)
            except ValueError:
                continue
    authors = list(dict.fromkeys(authors))[:12]
    contacts = {}
    def collect(parsed, source, names):
        for href, _, label in parsed.links:
            if not href.lower().startswith('mailto:'):
                continue
            try:
                email = outreach.email(href[7:])
            except ValueError:
                continue
            role = email.split('@')[0] in {'editor', 'editors', 'editorial', 'newsroom', 'tips', 'press'}
            if role:
                publisher = (urlsplit(url).hostname or '').lower().removeprefix('www.')
                email_domain = email.rsplit('@', 1)[1].lower()
                if email_domain != publisher and not email_domain.endswith('.' + publisher):
                    continue
            matched = [n for n in names if n.casefold() in label.casefold()]
            if not role and len(matched) != 1:
                continue
            contacts[email] = {'email': email, 'sourceUrl': source, 'kind': 'editorial' if role else 'author',
                               'name': 'Editorial inbox' if role else matched[0]}
    collect(article, url, authors)
    for target, names in list(profiles.items())[:2]:
        parsed = page(target)
        if parsed:
            collect(parsed, target, names)
    return {'authors': authors, 'contacts': list(contacts.values())[:20]}


async def execute(project, operation, data):
    backend = await storage.get_backend()
    base = work_actions.prefix(backend, project)
    if not await backend.get(storage.key(project, 'meta')):
        raise ValueError("Choose an existing project.")
    attempt = uuid.uuid4().hex
    store = await outreach.Records.open(backend, operation, {**data, '_attempt': attempt})
    if operation in ('citation_contact', 'citation_prospect_save'):
        url = fact_checks.clean_source(data.get('url'))
        term = outreach.text(data, 'term', 1500)
        project_data = await history.load_project(project)
        try:
            verify_citation(project_data, term, url)
        except ValueError:
            research = await store.read(base + ".research") or {}
            verify_citation(project_data, term, url, research.get("citations", []))
        found = await asyncio.to_thread(inspect_article, url)
        if operation == 'citation_contact':
            return {**found, 'url': url, 'term': term}
        contact = next((c for c in found['contacts'] if c['email'] == data.get('email')), None)
        if not contact:
            raise ValueError("Select an address explicitly credited by the publisher.")
        async with history.lock_for(project):
            pid = outreach.prospect_id(contact['email'])
            key = outreach.prospect_key(base, pid)
            previous = await store.read(key)
            result = ({'prospect': await outreach.view(store, base, previous)} if previous else
                      await outreach.save_prospect(store, base, {'email': contact['email'], 'recipientType': 'editor',
                        'sourceUrl': url, 'readerFit': term, 'asset': outreach.text(data, 'asset'),
                        'contactProvenance': contact['name'] + ' · ' + contact['sourceUrl']}))
            await store.private.set(key + '.citation', {**contact, 'url': url, 'term': term})
            return result

    pid = data.get('prospectId')
    key = outreach.prospect_key(base, pid)
    async with history.lock_for(project):
        version = data.get('version')
        if not isinstance(version, str) or not re.fullmatch('[0-9a-f]{32}', version):
            raise ValueError("Select the exact saved draft version.")
        slot = key + '.dispatch.' + version
        current = await store.read(slot)
        if operation == 'outreach_status':
            if not current:
                return {'status': 'unclaimed'}
            # The Google endpoint writes this record in the caller's selected Restricted
            # project KVS only after Gmail returns an actual message ID.
            receipt = await backend.get(storage.key(project, 'gmail-receipt', current['claimId']))
            expected = {'provider': 'gmail', 'prospectId': pid, 'claimId': current['claimId'],
                        'version': version, 'status': 'provider_accepted'}
            if (isinstance(receipt, dict) and all(receipt.get(k) == v for k, v in expected.items())
                    and isinstance(receipt.get('messageId'), str)
                    and re.fullmatch('[A-Za-z0-9_-]{1,160}', receipt['messageId'])):
                return {'status': 'provider_accepted', 'messageId': receipt['messageId']}
            if current.get('status') == 'provider_accepted' and current.get('messageId'):
                return {'status': 'provider_accepted', 'messageId': current['messageId']}
            return {'status': 'claimed'}
        if operation == 'outreach_finish':
            receipt = data.get('messageId')
            if (not current or current['claimId'] != data.get('claimId') or not isinstance(receipt, str)
                    or not re.fullmatch('[A-Za-z0-9_-]{1,160}', receipt)):
                raise ValueError("A verified provider receipt and matching claim are required.")
            if current.get('messageId') != receipt:
                if current.get('messageId'):
                    raise ValueError("This handoff already has a different receipt.")
                await store.write(slot, {'expected_revision': current['revision']}, current,
                                  {**current, 'messageId': receipt, 'status': 'provider_accepted'})
            return {'status': 'provider_accepted', 'messageId': receipt}
        if operation not in ('outreach_prepare', 'outreach_claim'):
            raise ValueError("Unknown citation outreach operation.")
        if current:
            raise ValueError("This version already has a mail handoff. Check the sender's Sent folder.")
        row = await outreach.view(store, base, await outreach.require_prospect(store, base, pid))
        draft = row.get('draft') or {}
        evidence = await store.private.get(key + '.citation')
        if not evidence or evidence['email'] != row['email'] or draft.get('version') != version or not draft.get('approved'):
            raise ValueError("Review and approve the current draft for a verified citation contact.")
        payload = {k: draft[k] for k in ('to', 'subject', 'body', 'version')}
        if operation == 'outreach_prepare':
            return {**payload, 'source': evidence}
        if data.get('confirm') is not True or any(data.get(k) != v for k, v in payload.items()):
            raise ValueError("Confirm the exact recipient, subject, body and version.")
        await store.write(slot, {}, None, {'claimId': attempt, 'status': 'claimed'})
        # Repeat suppression and approval checks after election, before releasing the send payload.
        final = await outreach.view(store, base, await outreach.require_prospect(store, base, pid))
        if not final['draft'] or not final['draft']['approved'] or final['draft']['version'] != version:
            raise ValueError("The recipient or draft changed. This handoff is closed.")
        return {**payload, 'claimId': attempt, 'status': 'claimed'}
