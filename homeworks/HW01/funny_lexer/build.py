# -*- coding: utf-8 -*-
from .regex_engine import regex_to_nfa
from .automata import union_nfas, subset_construction, epsilon_closure
from .minimize import hopcroft_minimize
from .token_specs import TOKEN_SPECS, ALPHABET


class BuildResult:
    def __init__(self):
        self.nfa = None
        self.nfa_state_count = None
        self.dfa = None
        self.dfa_state_count = None
        self.min_dfa = None
        self.min_dfa_state_count = None


def build_lexer_automaton(alphabet=None, token_specs=None):
    alphabet = alphabet or ALPHABET
    token_specs = token_specs or TOKEN_SPECS

    fragments = []
    for priority, (name, pattern) in enumerate(token_specs):
        frag_nfa = regex_to_nfa(pattern, alphabet, label=name)
        fragments.append((pattern, name, priority, frag_nfa))

    big_nfa, accepts_priority = union_nfas(fragments)

    dfa = subset_construction(big_nfa, accepts_priority, alphabet)
    min_dfa = hopcroft_minimize(dfa)

    res = BuildResult()
    res.nfa = big_nfa
    res.nfa_state_count = len(big_nfa.states)
    res.dfa = dfa
    res.dfa_state_count = len(dfa.states)
    res.min_dfa = min_dfa
    res.min_dfa_state_count = len(min_dfa.states)
    return res
