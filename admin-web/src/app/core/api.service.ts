import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  Account,
  Content,
  ContentDetail,
  Persona,
  Profile,
} from './models';

/** Thin wrapper over the FastAPI admin API (spec/admin_site.md §3). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  // reads
  profile(): Observable<Profile> {
    return this.http.get<Profile>('/api/profile');
  }
  personas(): Observable<Persona[]> {
    return this.http.get<Persona[]>('/api/personas');
  }
  account(): Observable<Account> {
    return this.http.get<Account>('/api/account');
  }
  queue(status: string): Observable<Content[]> {
    return this.http.get<Content[]>('/api/queue', { params: { status } });
  }
  upcoming(): Observable<Content[]> {
    return this.http.get<Content[]>('/api/upcoming');
  }
  content(id: string): Observable<ContentDetail> {
    return this.http.get<ContentDetail>(`/api/content/${id}`);
  }

  // transitions
  approve(id: string) {
    return this.http.post<Content>(`/api/content/${id}/approve`, {});
  }
  reject(id: string, reason: string) {
    return this.http.post<Content>(`/api/content/${id}/reject`, { reason });
  }
  unapprove(id: string) {
    return this.http.post<Content>(`/api/content/${id}/unapprove`, {});
  }
  retry(id: string) {
    return this.http.post<Content>(`/api/content/${id}/retry`, {});
  }

  // edit / recheck
  edit(id: string, text: string) {
    return this.http.post<Content>(`/api/content/${id}/edit`, { text });
  }
  editApprove(id: string, text: string) {
    return this.http.post<Content>(`/api/content/${id}/edit-approve`, { text });
  }
  recheckLlm(id: string) {
    return this.http.post<Content>(`/api/content/${id}/recheck-llm`, {});
  }

  // delete
  remove(id: string) {
    return this.http.delete<void>(`/api/content/${id}`);
  }

  // already-posted (stub 501 until poster P2)
  editPublished(id: string, text: string) {
    return this.http.post<void>(`/api/content/${id}/edit-published`, { text });
  }
  deletePublished(id: string) {
    return this.http.delete<void>(`/api/content/${id}/published`);
  }
}
