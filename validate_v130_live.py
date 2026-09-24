"""Live local-only smoke validation; separate from timed retrieval evaluation."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import resource
import socket
import subprocess
import sys
import threading
import time

# Enforce process-level external-network denial, preserving only loopback.
blocked=[]
def network_guard(event,args):
    if event=='socket.connect':
        address=args[1]
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
            blocked.append(str(address));raise PermissionError('External networking disabled for offline validation')
sys.addaudithook(network_guard)

import history_ai as h
from retrieval_config import load_config
from local_ui import Application
from offline_reader import OfflineReader
from libzim.reader import Archive
from conversation_state import ConversationState


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    config=load_config();hybrid=output/'hybrid.json';legacy=output/'legacy.json'
    h.save(hybrid,replace(config,retrieval_mode='hybrid').to_dict());h.save(legacy,replace(config,retrieval_mode='legacy').to_dict())
    reader=OfflineReader(Archive(str(h.ZIM_PATH)))
    stop=threading.Event();memory=[]
    def monitor():
        api=h.client()
        while not stop.wait(1):
            try:
                models=api.ps().get('models',[])
                memory.append({'time':time.time(),'models':[{'model':m['model'],'size':m.get('size'),'size_vram':m.get('size_vram')} for m in models]})
            except Exception:pass
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    report={'network_policy':'All non-loopback socket.connect denied in validation process',
            'checks':[],'models':h.client().list().model_dump(mode="json"),'swap_before':subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip()}
    cases=[('exact', 'In what year was Magna Carta first sealed?'),
           ('comparison','Compare the causes of the French and Russian Revolutions.'),
           ('chronology','What major events connected the assassination of Franz Ferdinand to the outbreak of World War I?')]
    try:
        for name,question in cases:
            for mode,path in [('legacy',legacy),('hybrid',hybrid)]:
                args=argparse.Namespace(question=question,model='qwen3:14b',config=path,index=None,top_k=None,
                     context_chars=None,num_predict=600,debug=True,quiet=True,output=output/f'{name}-{mode}.json')
                result=h.ask(args)
                resolved=[bool(reader.link(s['article_path'],s.get('section'),s.get('subsection'))) for s in result['sources']]
                check={'case':name,'mode':mode,'sources':len(resolved),'all_sources_resolve':all(resolved),
                       'unknown_citations':result.get('citation_check',{}).get('unknown_labels'),
                       'done_reason':result.get('done_reason'),'wall_seconds':result.get('wall_seconds'),
                       'prompt_tokens':result.get('prompt_eval_count'),
                       'estimated_prompt':result.get('generation_debug',{}).get('packing',{}).get('full_prompt_estimate')}
                report['checks'].append(check);h.save(output/'report.json',report)
                print(name,mode,json.dumps(check),flush=True)
        # Real multi-turn generation through Application persistence, including restart.
        def answer(args):
            args.config=hybrid;args.output=output/f'conversation-{time.time_ns()}.json'
            return h.ask(args)
        app=Application(reader,answer,output/'validation-chat.sqlite3')
        sid=None
        for question in ['Who was Gustavus Adolphus?','Why did he intervene in the Thirty Years’ War?','How did he die?','When was Magna Carta first sealed?']:
            result=app.run({'question':question,'model':'qwen3:14b','session':sid,'debug':True});sid=result['session']
            stored=app.store.load(sid)['turns'][-1]['result']
            print('followup',question,stored['analysis']['retrieval_query'],flush=True)
            report['checks'].append({'case':'followup','question':question,'query':stored['analysis']['retrieval_query'],
                   'sources':len(stored['sources']),'unknown_citations':stored.get('citation_check',{}).get('unknown_labels')})
        before=app.store.load(sid)['turns'];app.store.close()
        app=Application(reader,answer,output/'validation-chat.sqlite3')
        restored=app.store.load(sid)['turns'];assert before==restored
        response=app.run({'action':'open','session':sid})
        assert all(s['article_url'] for t in response['turns'] for s in t['result']['sources'])
        app.store.close();report['saved_chat_roundtrip']='exact match after restart; local citation URLs restored'
        args=argparse.Namespace(question='In what year was Magna Carta first sealed?',model='qwen3:8b',config=hybrid,index=None,
                 top_k=None,context_chars=None,num_predict=600,debug=True,quiet=True,output=output/'alternate-8b.json')
        result=h.ask(args);report['checks'].append({'case':'8b','answer':result['answer'],'unknown_citations':result['citation_check']['unknown_labels'],'done_reason':result.get('done_reason')})
        report['blocked_external_attempts']=blocked
        report['swap_after']=subprocess.check_output(['sysctl','vm.swapusage'],text=True).strip()
        report['process_peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    finally:
        stop.set();thread.join(timeout=3)
        report['memory_samples']=memory;h.save(output/'report.json',report)
    print('Live validation complete',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=h.ROOT/'artifacts/v130-live');args=p.parse_args();run(args.output)
