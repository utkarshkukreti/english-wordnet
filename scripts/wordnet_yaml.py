"""WordNet YAML interface"""
import yaml
from glob import glob
from wordnet import *
from yaml import CLoader
import codecs
import os
from collections import defaultdict

entry_orders = {}


def map_sense_key(sk):
    return sk


def make_pos(y, pos):
    if "adjposition" in y:
        return y["adjposition"] + "-" + pos
    else:
        return pos


def make_sense_id(y, lemma, pos):
    return "ewn-%s-%s-%s" % (
        escape_lemma(lemma), make_pos(y, pos), y["synset"][:-2])


def sense_from_yaml(y, lemma, pos, n):
    s = Sense(make_sense_id(y, lemma, pos),
              "ewn-" + y["synset"], map_sense_key(y["id"]), n,
              y.get("adjposition"))
    for rel, targets in y.items():
        if rel in SenseRelType._value2member_map_:
            for target in targets:
                # Remap senses
                s.add_sense_relation(SenseRelation(
                    map_sense_key(target), SenseRelType(rel)))
    return s


def synset_from_yaml(props, id, lex_name):
    if "partOfSpeech" not in props:
        print(props)
    ss = Synset("ewn-" + id,
                props.get("ili", "in"),
                PartOfSpeech(props["partOfSpeech"]),
                lex_name,
                props.get("source"))
    for defn in props["definition"]:
        ss.add_definition(Definition(defn))
    if "ili" not in props:
        ss.add_definition(Definition(props["definition"][0]), True)
    for example in props.get("example", []):
        if isinstance(example, str):
            ss.add_example(Example(example))
        else:
            ss.add_example(Example(example["text"], example["source"]))
    for rel, targets in props.items():
        if rel in SynsetRelType._value2member_map_:
            for target in targets:
                ss.add_synset_relation(SynsetRelation(
                    "ewn-" + target, SynsetRelType(rel)))
    return ss


def syntactic_behaviour_from_yaml(frames, props, lemma, pos):
    keys = set([subcat for sense in props["sense"]
                for subcat in sense.get("subcat", [])])
    return [
        SyntacticBehaviour(
            frames[k], [
                make_sense_id(
                    sense, lemma, pos) for sense in props["sense"] if k in sense.get(
                    "subcat", [])]) for k in keys]


def fix_sense_id(
        wn,
        sense,
        lemma,
        key2id,
        key2oldid,
        synset_ids_starting_from_zero):
    key2oldid[sense.sense_key] = sense.id
    idx = entry_orders[sense.synset[4:]].index(lemma)
    if sense.synset in synset_ids_starting_from_zero:
        sense.id = "%s-%02d" % (sense.id, idx)
    else:
        sense.id = "%s-%02d" % (sense.id, idx + 1)
    key2id[sense.sense_key] = sense.id
    wn.id2sense[sense.id] = sense
    wn.sense2synset[sense.id] = sense.synset


def fix_sense_rels(wn, sense, key2id, key2oldid):
    for rel in sense.sense_relations:
        if not rel.target.startswith("ewn-"):
            target_id = key2oldid[rel.target]
            rel.target = key2id[rel.target]
            if (rel.rel_type in inverse_sense_rels
                    and inverse_sense_rels[rel.rel_type] != rel.rel_type):
                wn.sense_by_id(target_id).add_sense_relation(
                    SenseRelation(sense.id,
                                  inverse_sense_rels[rel.rel_type]))


def fix_synset_rels(wn, synset):
    for rel in synset.synset_relations:
        if (rel.rel_type in inverse_synset_rels
                and inverse_synset_rels[rel.rel_type] != rel.rel_type):
            target_synset = wn.synset_by_id(rel.target)
            if not [sr for sr in target_synset.synset_relations if sr.target ==
                    synset.id and sr.rel_type == inverse_synset_rels[rel.rel_type]]:
                target_synset.add_synset_relation(
                    SynsetRelation(synset.id,
                                   inverse_synset_rels[rel.rel_type]))


def load():
    wn = Lexicon("ewn", "Engish WordNet", "en",
                 "english-wordnet@googlegroups.com",
                 "https://creativecommons.org/licenses/by/4.0",
                 "2020",
                 "https://github.com/globalwordnet/english-wordnet")
    with open("src/yaml/frames.yaml") as inp:
        frames = yaml.load(inp, Loader=CLoader)
    for f in glob("src/yaml/entries-*.yaml"):
        with open(f) as inp:
            y = yaml.load(inp, Loader=CLoader)

            for lemma, pos_map in y.items():
                for pos, props in pos_map.items():
                    entry = LexicalEntry(
                        "ewn-%s-%s" % (escape_lemma(lemma), pos))
                    entry.set_lemma(Lemma(lemma, PartOfSpeech(pos)))
                    if "form" in props:
                        for form in props["form"]:
                            entry.add_form(Form(form))
                    for n, sense in enumerate(props["sense"]):
                        entry.add_sense(sense_from_yaml(sense, lemma, pos, n))
                    entry.syntactic_behaviours = syntactic_behaviour_from_yaml(
                        frames, props, lemma, pos)
                    wn.add_entry(entry)

    for f in glob("src/yaml/*.yaml"):
        lex_name = f[9:-5]
        if "entries" not in f and "frames" not in f:
            with open(f) as inp:
                y = yaml.load(inp, Loader=CLoader)

                for id, props in y.items():
                    wn.add_synset(synset_from_yaml(props, id, lex_name))
                    entry_orders[id] = props["members"]

    # This is a big hack because of some inconsistencies in the XML that should
    # be gone soon
    synset_ids_starting_from_zero = set()
    for f in glob("src/xml/*.xml"):
        wn_lex = parse_wordnet(f)
        for entry in wn_lex.entries:
            for sense in entry.senses:
                if sense.id.endswith("00"):
                    synset_ids_starting_from_zero.add(sense.synset)

    key2id = {}
    key2oldid = {}
    for entry in wn.entries:
        for sense in entry.senses:
            fix_sense_id(
                wn,
                sense,
                entry.lemma.written_form,
                key2id,
                key2oldid,
                synset_ids_starting_from_zero)

    for entry in wn.entries:
        for sense in entry.senses:
            fix_sense_rels(wn, sense, key2id, key2oldid)

    for synset in wn.synsets:
        fix_synset_rels(wn, synset)

    by_lex_name = {}
    for synset in wn.synsets:
        if synset.lex_name not in by_lex_name:
            by_lex_name[synset.lex_name] = Lexicon(
                "ewn", "English WordNet", "en",
                "john@mccr.ae", "https://wordnet.princeton.edu/license-and-commercial-use",
                "2019", "https://github.com/globalwordnet/english-wordnet")
        by_lex_name[synset.lex_name].add_synset(synset)

    for entry in wn.entries:
        def find_sense_for_sb(sb_sense):
            for sense2 in entry.senses:
                if sense2.id[:-3] == sb_sense:
                    return sense2.id
            return None
        entry.syntactic_behaviours = [SyntacticBehaviour(
            sb.subcategorization_frame,
            [find_sense_for_sb(sense) for sense in sb.senses])
            for sb in entry.syntactic_behaviours]

    for lex_name, wn2 in by_lex_name.items():
        if os.path.exists("src/xml/wn-%s.xml" % lex_name):
            wn_lex = parse_wordnet("src/xml/wn-%s.xml" % lex_name)
            senseids = {
                sense.id[:-2]: sense.id for entry in wn_lex.entries for sense in entry.senses}
            for entry in wn2.entries:
                if wn_lex.entry_by_id(entry.id):
                    # Fix the last ID, because it is not actually so
                    # predicatable in the XML
                    for sense in entry.senses:
                        sense.id = senseids.get(sense.id[:-2], sense.id)

    return wn


def char_range(c1, c2):
    """Generates the characters from `c1` to `c2`, inclusive."""
    for c in range(ord(c1), ord(c2) + 1):
        yield chr(c)


def map_sense_key(sk):
    return sk


ignored_symmetric_sense_rels = set([
    SenseRelType.HAS_DOMAIN_REGION, SenseRelType.HAS_DOMAIN_TOPIC,
    SenseRelType.IS_EXEMPLIFIED_BY])


def sense_to_yaml(wn, s, sb_map):
    """Converts a single sense to the YAML form"""
    y = {}
    y["synset"] = s.synset[4:]
    y["id"] = map_sense_key(s.sense_key)
    if s.adjposition:
        y["adjposition"] = s.adjposition
    for sr in s.sense_relations:
        if sr.rel_type not in ignored_symmetric_sense_rels:
            if sr.rel_type.value not in y:
                if not wn.sense_by_id(sr.target):
                    print(sr.target)
                y[sr.rel_type.value] = [map_sense_key(
                    wn.sense_by_id(sr.target).sense_key)]
            else:
                y[sr.rel_type.value].append(map_sense_key(
                    wn.sense_by_id(sr.target).sense_key))
    if sb_map[s.id]:
        y["subcat"] = sorted(sb_map[s.id])
    return y


def definition_to_yaml(wn, d):
    """Convert a definition to YAML"""
    return d.text


def example_to_yaml(wn, x):
    """Convert an example to YAML"""
    if x.source:
        return {"text": x.text, "source": x.source}
    else:
        return x.text


frames = {
    "nonreferential": "It is ----ing",
    "nonreferential-sent": "It ----s that CLAUSE",
    "ditransitive": "Somebody ----s somebody something",
    "via": "Somebody ----s",
    "via-adj": "Somebody ----s Adjective",
    "via-at": "Somebody ----s at something",
    "via-for": "Somebody ----s for something",
    "via-ger": "Somebody ----s VERB-ing",
    "via-inf": "Somebody ----s INFINITIVE",
    "via-on-anim": "Somebody ----s on somebody",
    "via-on-inanim": "Somebody ----s on something",
    "via-out-of": "Somebody ----s out of somebody",
    "via-pp": "Somebody ----s PP",
    "via-that": "Somebody ----s that CLAUSE",
    "via-to": "Somebody ----s to somebody",
    "via-to-inf": "Somebody ----s to INFINITIVE",
    "via-whether-inf": "Somebody ----s whether INFINITIVE",
    "vibody": "Somebody's (body part) ----s",
    "vii": "Something ----s",
    "vii-adj": "Something ----s Adjective/Noun",
    "vii-inf": "Something ----s INFINITIVE",
    "vii-pp": "Something is ----ing PP",
    "vii-to": "Something ----s to somebody",
    "vtaa": "Somebody ----s somebody",
    "vtaa-inf": "Somebody ----s somebody INFINITIVE",
    "vtaa-into-ger": "Somebody ----s somebody into V-ing something",
    "vtaa-of": "Somebody ----s somebody of something",
    "vtaa-pp": "Somebody ----s somebody PP",
    "vtaa-to-inf": "Somebody ----s somebody to INFINITIVE",
    "vtaa-with": "Somebody ----s somebody with something",
    "vtai": "Somebody ----s something",
    "vtai-from": "Somebody ----s something from somebody",
    "vtai-on": "Somebody ----s something on somebody",
    "vtai-pp": "Somebody ----s something PP",
    "vtai-to": "Somebody ----s something to somebody",
    "vtai-with": "Somebody ----s something with something",
    "vtia": "Something ----s somebody",
    "vtii": "Something ----s something",
    "vtii-adj": "Something ----s something Adjective/Noun",
}

frames_inv = {v: k for k, v in frames.items()}

ignored_symmetric_synset_rels = set([
    SynsetRelType.HYPONYM, SynsetRelType.INSTANCE_HYPONYM,
    SynsetRelType.HOLONYM, SynsetRelType.HOLO_LOCATION,
    SynsetRelType.HOLO_MEMBER, SynsetRelType.HOLO_PART,
    SynsetRelType.HOLO_PORTION, SynsetRelType.HOLO_SUBSTANCE,
    SynsetRelType.STATE_OF,
    SynsetRelType.IS_CAUSED_BY, SynsetRelType.IS_SUBEVENT_OF,
    SynsetRelType.IN_MANNER, SynsetRelType.RESTRICTED_BY,
    SynsetRelType.CLASSIFIED_BY, SynsetRelType.IS_ENTAILED_BY,
    SynsetRelType.HAS_DOMAIN_REGION, SynsetRelType.HAS_DOMAIN_TOPIC,
    SynsetRelType.IS_EXEMPLIFIED_BY, SynsetRelType.INVOLVED,
    SynsetRelType.INVOLVED_AGENT, SynsetRelType.INVOLVED_PATIENT,
    SynsetRelType.INVOLVED_RESULT, SynsetRelType.INVOLVED_INSTRUMENT,
    SynsetRelType.INVOLVED_LOCATION, SynsetRelType.INVOLVED_DIRECTION,
    SynsetRelType.INVOLVED_TARGET_DIRECTION, SynsetRelType.INVOLVED_SOURCE_DIRECTION,
    SynsetRelType.CO_PATIENT_AGENT, SynsetRelType.CO_INSTRUMENT_AGENT,
    SynsetRelType.CO_RESULT_AGENT, SynsetRelType.CO_INSTRUMENT_PATIENT,
    SynsetRelType.CO_INSTRUMENT_RESULT])


def lemma2senseorder(wn, l, synset_id):
    for e2 in wn.entry_by_lemma(l):
        for sense in wn.entry_by_id(e2).senses:
            if sense.synset == synset_id:
                return sense.id[-2:]
    return "99"


def entries_ordered(wn, synset_id):
    """Get the lemmas for entries ordered correctly"""
    e = wn.members_by_id(synset_id)
    e.sort(key=lambda l: lemma2senseorder(wn, l, synset_id))
    return e


def save(wn, change_list=None):
    entry_yaml = {c: {} for c in char_range('a', 'z')}
    entry_yaml['0'] = {}
    for entry in wn.entries:
        e = {}
        if entry.forms:
            e['form'] = [f.written_form for f in entry.forms]

        sb_map = defaultdict(lambda: [])
        for sb in entry.syntactic_behaviours:
            sb_name = frames_inv[sb.subcategorization_frame]
            for sense in sb.senses:
                sb_map[sense].append(sb_name)

        e['sense'] = [sense_to_yaml(wn, s, sb_map) for s in entry.senses]

        first = entry.lemma.written_form[0].lower()
        if first not in char_range('a', 'z'):
            first = '0'
        if entry.lemma.written_form not in entry_yaml[first]:
            entry_yaml[first][entry.lemma.written_form] = {}
        if entry.lemma.part_of_speech.value in entry_yaml[first][entry.lemma.written_form]:
            print(
                "Duplicate: %s - %s" %
                (entry.lemma.written_form,
                 entry.lemma.part_of_speech.value))
        entry_yaml[first][entry.lemma.written_form][entry.lemma.part_of_speech.value] = e

    for c in char_range('a', 'z'):
        if not change_list or c in change_list.entry_files:
            with open("src/yaml/entries-%s.yaml" % c, "w") as outp:
                outp.write(yaml.dump(entry_yaml[c], default_flow_style=False))
    if not change_list or '0' in change_list.entry_files:
        with open("src/yaml/entries-0.yaml", "w") as outp:
            outp.write(yaml.dump(entry_yaml['0'], default_flow_style=False))

    synset_yaml = {}
    for synset in wn.synsets:
        s = {}
        if synset.ili and synset.ili != "in":
            s["ili"] = synset.ili
        s["partOfSpeech"] = synset.part_of_speech.value
        s["definition"] = [
            definition_to_yaml(
                wn, d) for d in synset.definitions]
        if synset.examples:
            s["example"] = [example_to_yaml(wn, x) for x in synset.examples]
        if synset.source:
            s["source"] = synset.source
        for r in synset.synset_relations:
            if r.rel_type not in ignored_symmetric_synset_rels:
                if r.rel_type.value not in s:
                    s[r.rel_type.value] = [r.target[4:]]
                else:
                    s[r.rel_type.value].append(r.target[4:])
        if synset.lex_name not in synset_yaml:
            synset_yaml[synset.lex_name] = {}
        synset_yaml[synset.lex_name][synset.id[4:]] = s
        s["members"] = entries_ordered(wn, synset.id)

    for key, synsets in synset_yaml.items():
        if not change_list or key in change_list.lexfiles:
            with open("src/yaml/%s.yaml" % key, "w") as outp:
                outp.write(yaml.dump(synsets, default_flow_style=False))

    with open("src/yaml/frames.yaml", "w") as outp:
        outp.write(yaml.dump(frames, default_flow_style=False))
