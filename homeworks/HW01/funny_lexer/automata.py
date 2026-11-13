# -*- coding: utf-8 -*-
"""
Subset construction (НКА -> ДКА) + структура данных ДКА.
"""
from .regex_engine import NFA


TRAP = "TRAP"  # id ловушки в итоговом ДКА


def union_nfas(fragments):
    """
    fragments: list of (pattern, label, priority, NFA)  -- каждая NFA уже построена
    отдельно (Thompson) со своей нумерацией состояний 0..k.
    Возвращает единый NFA с новым стартовым состоянием (eps-переходы к каждому
    фрагменту) и картой accepts: state -> (label, priority).
    Состояния всех фрагментов перенумеровываются, чтобы не пересекались.
    """
    big = NFA()
    start = big.new_state()
    accepts_priority = {}  # state -> (label, priority)

    for pattern, label, priority, frag_nfa in fragments:
        offset = {}
        for s in frag_nfa.states:
            offset[s] = big.new_state()
        for (s_from, sym), tos in frag_nfa.trans.items():
            ns_from = offset[s_from]
            for s_to in tos:
                big.add_edge(ns_from, sym, offset[s_to])
        big.add_edge(start, None, offset[frag_nfa.start])
        for acc_state, acc_label in frag_nfa.accepts.items():
            accepts_priority[offset[acc_state]] = (acc_label, priority)

    big.start = start
    return big, accepts_priority


def epsilon_closure(nfa, states):
    stack = list(states)
    closure = set(states)
    while stack:
        s = stack.pop()
        for t in nfa.trans.get((s, None), ()):
            if t not in closure:
                closure.add(t)
                stack.append(t)
    return frozenset(closure)


def move(nfa, states, symbol):
    result = set()
    for s in states:
        result |= nfa.trans.get((s, symbol), set())
    return result


class DFA:
    """
    states: set of state ids (ints), including TRAP
    trans: dict[(state, symbol)] -> state   (total function over `alphabet`)
    start: int
    accepts: dict[state -> label]   (TRAP and dead states are never in accepts)
    alphabet: iterable of symbols (chars) used to build/complete the table
    """
    def __init__(self, alphabet):
        self.states = set()
        self.trans = {}
        self.start = None
        self.accepts = {}
        self.alphabet = list(alphabet)
        self.trap_state = TRAP

    def step(self, state, symbol):
        return self.trans.get((state, symbol), TRAP)


def subset_construction(nfa, accepts_priority, alphabet):
    """
    Классический subset construction с явным построением ПОЛНОГО (complete)
    ДКА: все "непокрытые" переходы ведут в явное состояние-ловушку TRAP,
    из которого нет выхода ни по одному символу алфавита (self-loop trap).
    """
    dfa = DFA(alphabet)

    start_set = epsilon_closure(nfa, {nfa.start})
    set_to_id = {start_set: 0}
    dfa.start = 0
    dfa.states.add(0)
    worklist = [start_set]

    def label_for(state_set):
        # среди всех NFA-принимающих состояний в этом подмножестве выбираем
        # то, что имеет наивысший приоритет (наименьшее число priority)
        best = None
        for s in state_set:
            if s in accepts_priority:
                lbl, prio = accepts_priority[s]
                if best is None or prio < best[1]:
                    best = (lbl, prio)
        return best[0] if best else None

    lbl = label_for(start_set)
    if lbl is not None:
        dfa.accepts[0] = lbl

    while worklist:
        cur_set = worklist.pop()
        cur_id = set_to_id[cur_set]
        for symbol in alphabet:
            mv = move(nfa, cur_set, symbol)
            if not mv:
                continue  # ничего не определено -> неявно TRAP
            closure = epsilon_closure(nfa, mv)
            if closure not in set_to_id:
                new_id = len(set_to_id)
                set_to_id[closure] = new_id
                dfa.states.add(new_id)
                lbl = label_for(closure)
                if lbl is not None:
                    dfa.accepts[new_id] = lbl
                worklist.append(closure)
            dfa.trans[(cur_id, symbol)] = set_to_id[closure]

    # добавляем явную ловушку и достраиваем ДКА до полного (total)
    dfa.trap_state = TRAP
    dfa.states.add(TRAP)
    for symbol in alphabet:
        dfa.trans[(TRAP, symbol)] = TRAP
    for st in list(dfa.states):
        if st == TRAP:
            continue
        for symbol in alphabet:
            if (st, symbol) not in dfa.trans:
                dfa.trans[(st, symbol)] = TRAP

    return dfa
