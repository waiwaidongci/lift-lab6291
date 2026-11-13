import {request} from './client';
import {Dataset, DatasetImport, DatasetVersion, Experiment, Observation} from '../types/domain';

export const getDatasets = () => request<Dataset[]>('/datasets');
export const getDataset = (id: number) => request<Dataset>(`/datasets/${id}`);
export const getObservations = (id: number, version?: number) =>
  request<Observation[]>(`/datasets/${id}/observations${version ? `?version=${version}` : ''}`);
export const getVersions = (id: number) => request<DatasetVersion[]>(`/datasets/${id}/versions`);
export const getImports = (id: number) => request<DatasetImport[]>(`/datasets/${id}/imports`);
export const getUsage = (id: number) =>
  request<(Experiment & {version: number | null})[]>(`/datasets/${id}/usage`);
export const createDataset = (data: {name: string; source: string; description: string}) =>
  request<Dataset>('/datasets', {method: 'POST', body: JSON.stringify(data)});

export async function importObservations(id: number, file: File, description: string) {
  const body = new FormData();
  body.append('file', file);
  body.append('description', description);
  const response = await fetch(`/api/datasets/${id}/import`, {
    method: 'POST',
    headers: {Authorization: 'Bearer ' + localStorage.getItem('lift-token')},
    body,
  });
  const payload = await response.json().catch(() => ({detail: '网络异常'}));
  if (!response.ok) {
    const error = new Error(typeof payload.message === 'string'
      ? payload.message
      : typeof payload.detail === 'string' ? payload.detail : '导入失败') as Error & {
      errors?: {line: number; subject: string; reason: string}[];
    };
    error.errors = payload.errors;
    throw error;
  }
  return payload as ImportResult;
}

export interface ImportResult {
  status: 'published' | 'duplicate' | 'rejected';
  version: DatasetVersion | null;
  import_id: number;
  message: string;
  filename: string;
  rows_received: number;
  rows_unique: number;
  duplicates_removed: number;
  errors: {line: number; subject: string; reason: string}[];
}
