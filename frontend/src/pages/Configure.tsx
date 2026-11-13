import {FormEvent,useEffect,useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {ArrowRight} from 'lucide-react';
import {useResearchData} from '../hooks/useResearch';
import {createExperiment} from '../api/experiments';
import {enqueueRun} from '../api/runs';
import {getVersions} from '../api/datasets';
import {DatasetVersion} from '../types/domain';
import {useAction} from '../hooks/useAction';
import {useAuth} from '../stores/auth';
import {Notice} from '../components/common/Notice';

export function Configure(){
  const s=useResearchData(),{user}=useAuth(),action=useAction(),navigate=useNavigate();
  const [name,setName]=useState(''),[hypothesis,setHypothesis]=useState(''),[alpha,setAlpha]=useState(.05),[cuped,setCuped]=useState(true),[did,setDid]=useState(0),[vid,setVid]=useState(0),[versions,setVersions]=useState<DatasetVersion[]>([]);
  const dataset=s.datasets.find(d=>d.id===did)||s.datasets[0];
  const selected=versions.find(v=>v.version===vid)||versions[0];

  useEffect(()=>{
    if(!dataset){setVersions([]);return}
    getVersions(dataset.id).then(rows=>{setVersions(rows);setVid(rows[0]?.version||0)}).catch(()=>setVersions([]));
  },[dataset?.id]);

  function submit(e:FormEvent){e.preventDefault();action.execute(async()=>{
    const exp=await createExperiment({name,hypothesis,dataset_id:did||s.datasets[0]?.id,version:vid||selected?.version,alpha,cuped});
    await enqueueRun(exp.id);
    navigate('/runs');
  })}

  return <div className="page">
    <div className="page-title"><div><p className="eyebrow">PRE-REGISTRATION / 03</p><h1>实验配置<span>先写假设，再看结果。</span></h1></div></div>
    <div className="editor-layout">
      <form className="research-form" onSubmit={submit}>
        <h2><span>01</span> 定义研究问题</h2>
        <label>实验名称<input aria-label="实验名称" value={name} onChange={e=>setName(e.target.value)} placeholder="例如：短文付费入口 v4" minLength={2} maxLength={120} required disabled={user?.role==='viewer'}/></label>
        <label>可检验的业务假设<textarea aria-label="业务假设" value={hypothesis} onChange={e=>setHypothesis(e.target.value)} placeholder="描述改动、预期影响与观测指标，至少8字。" minLength={8} required disabled={user?.role==='viewer'}/></label>
        <h2><span>02</span> 固定分析口径</h2>
        <label>观测数据<select value={did} onChange={e=>setDid(Number(e.target.value))}><option value="0">选择已冻结数据</option>{s.datasets.map(d=><option key={d.id} value={d.id}>{d.name} / v{d.latest_version} / {d.observations} 位用户</option>)}</select></label>
        <label>观测版本<select aria-label="观测版本" value={selected?.version||0} onChange={e=>setVid(Number(e.target.value))} disabled={!versions.length}>{versions.length?versions.map(v=><option key={v.id} value={v.version}>v{v.version} · {v.rows_unique} 位用户 · {v.source}</option>):<option value="0">该数据集尚未发布版本</option>}</select><small>登记后实验固定在所选版本；之后上传的新版本不会改动本实验的复算依据。</small></label>
        <div className="form-pair">
          <label>显著性水平 α<select value={alpha} onChange={e=>setAlpha(Number(e.target.value))}><option value="0.05">0.05 / 95% 区间</option><option value="0.01">0.01 / 99% 区间</option><option value="0.1">0.10 / 90% 区间</option></select></label>
          <label>分析指标<input value="每用户7日收入 / revenue" readOnly/></label>
        </div>
        <label className="checkbox"><input type="checkbox" checked={cuped} onChange={e=>setCuped(e.target.checked)}/><span>使用前置收入执行 CUPED 方差校正<small>同时保留未经校正的 Welch 对照结果。</small></span></label>
        <Notice message={action.error||s.error}/>
        {user?.role==='viewer'?<p className="notice">观察员可阅读配置；登记与运行需要分析师权限。</p>:<button className="primary" disabled={action.busy||!versions.length}>{action.busy?'提交中…':'登记并提交分析'}<ArrowRight size={17}/></button>}
      </form>
      <aside className="method-note">
        <span className="eyebrow">METHOD NOTE / 01</span>
        <h2>关于这次计算</h2>
        <ol>
          <li><b>Welch t 检验</b><p>允许两组方差不等，返回双侧 p 值、自由度与均值差区间。</p></li>
          <li><b>CUPED 校正</b><p>以分桶前收入作协变量，降低噪声；不改变随机分桶。</p></li>
          <li><b>版本固定</b><p>本次分析只读取登记时选定的观测版本；后补数据形成新版本，旧实验结论仍可复算。</p></li>
          <li><b>明确边界</b><p>至少每组3人；常量和非有限观测会使任务失败。结果不替代业务审核。</p></li>
        </ol>
      </aside>
    </div>
  </div>;
}
