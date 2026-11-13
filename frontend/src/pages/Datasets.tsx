import { ChangeEvent, useEffect, useState } from 'react';
import { Database, Fingerprint, Upload, History, FileWarning, FolderPlus } from 'lucide-react';
import { useResearchData } from '../hooks/useResearch';
import { useAuth } from '../stores/auth';
import {
  createDataset, getImports, getObservations, getUsage, getVersions,
  importObservations, ImportResult,
} from '../api/datasets';
import { DatasetImport, DatasetVersion, Experiment, Observation } from '../types/domain';
import { DataTable } from '../components/common/DataTable';
import { Notice } from '../components/common/Notice';
import { number, time } from '../utils/format';
import { ImportStatus } from '../constants/enums';

type Usage = Experiment & { version: number | null };

export function Datasets() {
  const research = useResearchData();
  const { user } = useAuth();
  const canImport = user?.role === 'admin' || user?.role === 'analyst';
  const [selectedId, setSelectedId] = useState(0);
  const dataset = research.datasets.find(d => d.id === selectedId) || research.datasets[0];
  const [version, setVersion] = useState<number | undefined>(undefined);
  const [rows, setRows] = useState<Observation[]>([]);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [imports, setImports] = useState<DatasetImport[]>([]);
  const [usage, setUsage] = useState<Usage[]>([]);
  const [error, setError] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [rejection, setRejection] = useState<{ line: number; subject: string; reason: string }[]>([]);
  const [newName, setNewName] = useState('');
  const [newSource, setNewSource] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  async function addDataset() {
    setBusy(true);
    setError('');
    try {
      const created = await createDataset({
        name: newName, source: newSource, description: '',
      });
      setNewName('');
      setNewSource('');
      setShowCreate(false);
      await research.refresh();
      setSelectedId(created.id);
      setVersion(undefined);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reload(id: number, v?: number) {
    try {
      const [preview, history, journal, users] = await Promise.all([
        getObservations(id, v), getVersions(id), getImports(id), getUsage(id),
      ]);
      setRows(preview);
      setVersions(history);
      setImports(journal);
      setUsage(users);
      setError('');
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    if (dataset) reload(dataset.id, version);
  }, [dataset?.id, version]);

  useEffect(() => setVersion(undefined), [dataset?.id]);

  async function upload() {
    if (!dataset || !file) return;
    setBusy(true);
    setError('');
    setResult(null);
    setRejection([]);
    try {
      const response = await importObservations(dataset.id, file, description);
      setResult(response);
      setVersion(undefined);
      setFile(null);
      setDescription('');
      await research.refresh();
      await reload(dataset.id);
    } catch (e) {
      const failure = e as Error & { errors?: { line: number; subject: string; reason: string }[] };
      setRejection(failure.errors || []);
      setError(failure.message);
      await research.refresh();
      await reload(dataset.id, version);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <p className="eyebrow">OBSERVATION REGISTER / 02</p>
          <h1>观测数据<span>让每个样本有据可查。</span></h1>
        </div>
        <Database size={32} />
      </div>
      <Notice message={research.error || error} retry={research.refresh} />

      {research.datasets.length > 1 && (
        <label className="dataset-select">
          数据集
          <select value={dataset?.id || 0} onChange={e => setSelectedId(Number(e.target.value))}>
            {research.datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
      )}

      {canImport && (
        <div className="dataset-select">
          {showCreate ? (
            <div className="create-dataset">
              <label>数据集名称<input value={newName} onChange={e => setNewName(e.target.value)} placeholder="例如：付费入口 · 12月实验" minLength={2} maxLength={120} /></label>
              <label>来源文件<input value={newSource} onChange={e => setNewSource(e.target.value)} placeholder="例如：lanqiao-paywall-2026-12.csv" maxLength={200} /></label>
              <button className="primary" disabled={busy || newName.trim().length < 2} onClick={addDataset}>创建数据集</button>
              <button className="text-button" onClick={() => setShowCreate(false)}>取消</button>
            </div>
          ) : (
            <button className="text-button" onClick={() => setShowCreate(true)}>
              <FolderPlus size={15} /> 新建数据集
            </button>
          )}
        </div>
      )}

      {dataset ? <>
        <div className="dataset-banner">
          <div>
            <span className="eyebrow">FROZEN SOURCE / 已发布版本</span>
            <h2>{dataset.name}</h2>
            <p>{dataset.description || '未填写来源说明。'}</p>
            <code>{dataset.source || '—'}</code>
          </div>
          <div>
            <strong>{dataset.observations.toLocaleString()}</strong>
            <span>当前版本独立用户观测</span>
            <small><Fingerprint size={15} />{dataset.checksum.slice(0, 16) || '—'}…</small>
            <small>v{dataset.latest_version} · 共 {dataset.versions} 个版本</small>
          </div>
        </div>

        <div className="import-panel">
          <h2><Upload size={17} /> 导入观测文件</h2>
          <p>
            上传 CSV（列：subject, arm, pre_value, value；分组接受 control / treatment）。同一匿名样本内容相同只保留一条记录；
            分组或数值冲突时整批拒绝并给出行号。内容相同（换行序也算）不会新增版本。
          </p>
          {canImport ? (
            <div className="import-controls">
              <label>
                观测文件
                <input type="file" accept=".csv,text/csv"
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setFile(e.target.files?.[0] || null)} />
              </label>
              <label>
                版本说明（可选）
                <input value={description} onChange={e => setDescription(e.target.value)}
                  placeholder="例如：11 月补传，替换缺失样本" maxLength={200} />
              </label>
              <button className="primary" disabled={busy || !file} onClick={upload}>
                <Upload size={16} />{busy ? '校验并发布中…' : '导入并发布版本'}
              </button>
            </div>
          ) : <p className="notice">观察员可核对版本与样本；导入需要分析师或负责人权限。</p>}

          {result && (
            <div className={'import-result ' + result.status}>
              <b>{ImportStatus[result.status as keyof typeof ImportStatus] || result.status}</b>
              <span>{result.message}</span>
              <small>
                收到 {result.rows_received} 行 · 唯一 {result.rows_unique} 行 · 合并重复 {result.duplicates_removed} 行
                {result.version && <> · v{result.version.version} · 来源 {result.version.source}</>}
              </small>
            </div>
          )}
          {rejection.length > 0 && (
            <div className="rejection">
              <h3><FileWarning size={17} /> 拒绝原因（共 {rejection.length} 条）</h3>
              <DataTable head={['文件行号', '匿名样本', '原因']}>
                {rejection.map((e, i) => (
                  <tr key={`${e.line}-${i}`}>
                    <td className="mono">{e.line || '—'}</td>
                    <td className="mono">{e.subject || '—'}</td>
                    <td>{e.reason}</td>
                  </tr>
                ))}
              </DataTable>
            </div>
          )}
        </div>

        <div className="section-heading">
          <h2><History size={18} /> 版本记录</h2>
          <span>VERSION HISTORY / {versions.length}</span>
        </div>
        <DataTable head={['版本', '来源文件', '唯一观测', '合并重复', '内容指纹', '发布人 / 时间', '预览']}>
          {versions.map(v => (
            <tr key={v.id}>
              <td><b>v{v.version}</b></td>
              <td className="mono">{v.source}</td>
              <td>{number(v.rows_unique, 0)}</td>
              <td>{number(v.duplicates_removed, 0)}</td>
              <td className="mono">{v.checksum.slice(0, 16)}…</td>
              <td><small>{v.created_by}</small><span>{time(v.created_at)}</span></td>
              <td>
                <button className="text-button" onClick={() => setVersion(v.version)}>
                  {version === v.version ? '正在预览' : '查看该版本'}
                </button>
              </td>
            </tr>
          ))}
        </DataTable>

        <div className="section-heading">
          <h2>实验与版本来源</h2>
          <span>按登记时固定的观测版本复算</span>
        </div>
        <DataTable head={['实验', '固定版本', '负责人']}>
          {usage.length ? usage.map(e => (
            <tr key={e.id}>
              <td><b>{e.name}</b></td>
              <td>{e.version ? `v${e.version}` : '未固定'}</td>
              <td>{e.owner}</td>
            </tr>
          )) : <tr><td colSpan={3}>尚无实验登记在该数据集上。</td></tr>}
        </DataTable>

        <div className="section-heading">
          <h2>导入记录</h2>
          <span>IMPORT JOURNAL / 最近 50 次</span>
        </div>
        <DataTable head={['时间', '文件', '结果', '说明', '行数', '操作者']}>
          {imports.map(row => (
            <tr key={row.id}>
              <td>{time(row.created_at)}</td>
              <td className="mono">{row.filename}</td>
              <td className={row.status}>{ImportStatus[row.status as keyof typeof ImportStatus] || row.status}</td>
              <td>{row.reason || '—'}</td>
              <td>{row.rows_received} / {row.rows_unique}</td>
              <td>{row.actor}</td>
            </tr>
          ))}
        </DataTable>

        <div className="section-heading">
          <h2>样本预览</h2>
          <span>
            {version ? `v${version} / 已选版本` : `v${dataset.latest_version} / 最新版本`} · 前 100 条
          </span>
        </div>
        {version && (
          <button className="text-button" onClick={() => setVersion(undefined)}>返回最新版本</button>
        )}
        <DataTable head={['匿名用户', '实验分组', '前置7日收入 / 元', '后置7日收入 / 元']}>
          {rows.map(o => (
            <tr key={o.subject}>
              <td className="mono">{o.subject}</td>
              <td><span className={'arm ' + o.arm}>{o.arm === 'control' ? '对照组' : '候选组'}</span></td>
              <td>{number(o.pre_value)}</td>
              <td>{number(o.value)}</td>
            </tr>
          ))}
        </DataTable>
      </> : <p>尚无观测数据。负责人可先创建数据集，再从页面导入观测文件。</p>}
    </div>
  );
}
