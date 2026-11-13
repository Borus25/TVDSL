# -*- coding: utf-8 -*-
"""
Экспорт таблицы переходов ДКА в JSON и CSV -- в формате, пригодном для
подключения к лексеру проекта (контрольная точка T0).

JSON-схема:
{
  "alphabet_size": 128,
  "start": 0,
  "trap": 37,
  "states": [0, 1, 2, ...],
  "accepts": {"5": "IDENT", "9": "KW_IF", ...},
  "transitions": {"0": {"97": 1, "98": 2, ...}, ...}   # state -> {char_code: next_state}
}

CSV-схема (одна строка на переход): state,symbol_code,symbol_repr,next_state
плюс отдельные строки-метаданные с префиксом '#'.
"""
import json
import csv


def _state_key(s):
    return str(s)


def dfa_to_json_dict(dfa):
    states_sorted = sorted(dfa.states, key=lambda s: (isinstance(s, str), str(s)))
    accepts = {_state_key(s): lbl for s, lbl in dfa.accepts.items()}
    transitions = {}
    for s in dfa.states:
        row = {}
        for sym in dfa.alphabet:
            dst = dfa.trans.get((s, sym))
            if dst is None:
                continue
            row[str(ord(sym))] = _state_key(dst)
        transitions[_state_key(s)] = row
    return {
        "alphabet_size": len(dfa.alphabet),
        "start": _state_key(dfa.start),
        "trap": _state_key(dfa.trap_state),
        "states": [_state_key(s) for s in states_sorted],
        "accepts": accepts,
        "transitions": transitions,
    }


def export_json(dfa, path):
    data = dfa_to_json_dict(dfa)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def export_csv(dfa, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["#start", dfa.start])
        w.writerow(["#trap", dfa.trap_state])
        for s, lbl in sorted(dfa.accepts.items(), key=lambda kv: str(kv[0])):
            w.writerow(["#accept", s, lbl])
        w.writerow(["state", "symbol_code", "symbol_repr", "next_state"])
        for s in sorted(dfa.states, key=lambda x: str(x)):
            for sym in dfa.alphabet:
                dst = dfa.trans.get((s, sym))
                if dst is None:
                    continue
                repr_sym = sym
                if sym in ("\n", "\r", "\t"):
                    repr_sym = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}[sym]
                elif sym == ",":
                    repr_sym = "<comma>"
                w.writerow([s, ord(sym), repr_sym, dst])
