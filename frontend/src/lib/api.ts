export async function api<T>(path:string, options?:RequestInit):Promise<T>{
  const response=await fetch(`/api${path}`,{headers:{...(options?.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options?.headers},...options})
  if(!response.ok) throw new Error((await response.json().catch(()=>({detail:'Request failed'}))).detail||'Request failed')
  if(response.status===204) return undefined as T
  return response.json()
}
export function bytes(value:number){const units=['B','KB','MB','GB','TB'];let index=0;while(value>=1024&&index<4){value/=1024;index++}return `${value.toFixed(index?1:0)} ${units[index]}`}
