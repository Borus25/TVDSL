"""P09 request-response protocol: one model and explicit mutations."""
from copy import deepcopy


def models():
    original={'name':'original','initial':'s0',
              'transitions':{'s0':['s1'],'s1':['s1','s2'],'s2':['s0'],'s3':['s3']},
              'labels':{'s0':['idle'],'s1':['req'],'s2':['ack'],'s3':['error']},
              'fairness':[],
              'description':'P09 original; unbounded waiting allowed; no fairness'}
    fixed=deepcopy(original);fixed['name']='fixed'
    fixed['transitions']['s1']=['s2']
    fixed['description']='Remove only s1->s1: request must advance to ack'
    error=deepcopy(original);error['name']='error_transition'
    error['transitions']['s1'].append('s3')
    error['description']='Add s1->s3, making error reachable'
    overlap=deepcopy(error);overlap['name']='overlap_labels'
    overlap['labels']['s3']=['error','req','ack']
    overlap['description']='Add req and ack labels simultaneously at reachable s3'
    bad_ack=deepcopy(fixed);bad_ack['name']='bad_ack_successor'
    bad_ack['transitions']['s2']=['s0','s1']
    bad_ack['description']='Add ack->req transition, violating ack->X idle'
    return [original,fixed,error,overlap,bad_ack]


PROPERTIES=[
    {'id':'p01_no_error','category':'safety','logic':'CTL','formula':'AG (!error)',
     'description':'Ошибка никогда не достигается.',
     'ctl':('AG',('not','error'))},
    {'id':'p02_no_overlap','category':'safety','logic':'LTL','formula':'G (!(req & ack))',
     'description':'Запрос и подтверждение не активны одновременно.',
     'ctl':('AG',('not',('and','req','ack')))},
    {'id':'p03_ack_to_idle','category':'safety','logic':'LTL','formula':'G (ack -> X idle)',
     'description':'После подтверждения следующим состоянием является idle.',
     'ctl':('AG',('or',('not','ack'),('AX','idle')))},
    {'id':'p04_response','category':'liveness','logic':'LTL','formula':'G (req -> F ack)',
     'description':'Каждый запрос когда-нибудь получает подтверждение.',
     'ctl':('AG',('or',('not','req'),('AF','ack')))},
    {'id':'p05_recurring_ack','category':'liveness','logic':'LTL','formula':'G F ack',
     'description':'Подтверждения происходят бесконечно часто.',
     'ctl':('AG',('AF','ack'))},
    {'id':'p06_error_reachable','category':'existential_reachability','logic':'CTL','formula':'EF error',
     'description':'Существует путь к ошибке: диагностический запрос, его ложность ожидаема в исправной модели.',
     'ctl':('EF','error')},
]

EXPECTED={
    'original':[True,True,True,False,False,False],
    'fixed':[True,True,True,True,True,False],
    'error_transition':[False,True,True,False,False,True],
    'overlap_labels':[False,False,False,False,False,True],
    'bad_ack_successor':[True,True,False,True,True,False],
}
