# -*- coding: utf-8 -*-
"""
Минимизация ДКА алгоритмом Хопкрофта.

Отличие от «учебной» версии (F / Q\\F): у нас несколько принимающих классов
(по одному на тип токена) плюс класс непринимающих состояний (включая
ловушку). Поэтому начальное разбиение строится не по бинарному признаку
"принимает/не принимает", а по равенству меток (label), где непринимающие
состояния получают метку None.

P (партиция) хранится как список frozenset состояний.
W (worklist) -- список тех же множеств, которые ещё нужно использовать
как "разделители".
"""
from .automata import DFA, TRAP


def hopcroft_minimize(dfa):
    alphabet = dfa.alphabet
    states = list(dfa.states)

    # 1) начальное разбиение по меткам (None для непринимающих, включая TRAP)
    groups = {}
    for s in states:
        lbl = dfa.accepts.get(s)  # None если не принимающее (в т.ч. TRAP)
        groups.setdefault(lbl, set()).add(s)

    P = [frozenset(g) for g in groups.values()]
    W = list(P)

    # предвычисление обратных переходов: (symbol) -> dict(dst -> set(src))
    rev = {sym: {} for sym in alphabet}
    for (s_from, sym), s_to in dfa.trans.items():
        rev[sym].setdefault(s_to, set()).add(s_from)

    def split(A):
        """для множества A по каждому символу считаем X = {q : delta(q,c) in A}"""
        for c in alphabet:
            X = set()
            for a in A:
                X |= rev[c].get(a, set())
            if not X:
                continue
            yield frozenset(X)

    while W:
        A = W.pop()
        for c in alphabet:
            X = set()
            for a in A:
                X |= rev[c].get(a, set())
            if not X:
                continue
            newP = []
            for Y in P:
                inter = Y & X
                diff = Y - X
                if inter and diff:
                    newP.append(frozenset(inter))
                    newP.append(frozenset(diff))
                    if Y in W:
                        W.remove(Y)
                        W.append(frozenset(inter))
                        W.append(frozenset(diff))
                    else:
                        if len(inter) <= len(diff):
                            W.append(frozenset(inter))
                        else:
                            W.append(frozenset(diff))
                else:
                    newP.append(Y)
            P = newP

    # 2) строим минимизированный ДКА по классам эквивалентности P
    class_of = {}
    for idx, group in enumerate(P):
        for s in group:
            class_of[s] = idx

    trap_class = class_of[TRAP]

    min_dfa = DFA(alphabet)
    min_dfa.start = class_of[dfa.start]

    for idx, group in enumerate(P):
        if idx == trap_class:
            continue  # ловушку не включаем как "обычное" состояние-имя,
            # но она всё равно достижима как id класса trap_class
        min_dfa.states.add(idx)
    min_dfa.states.add(trap_class)  # ловушка в минимизированном автомате

    for idx, group in enumerate(P):
        rep = next(iter(group))
        for c in alphabet:
            dst = dfa.trans[(rep, c)]
            min_dfa.trans[(idx, c)] = class_of[dst]
        if rep in dfa.accepts:
            min_dfa.accepts[idx] = dfa.accepts[rep]

    min_dfa.trap_state = trap_class
    return min_dfa
