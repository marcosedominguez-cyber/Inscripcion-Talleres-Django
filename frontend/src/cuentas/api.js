import { solicitudApi } from '../api.js';

export function api(path, datos) {
  return solicitudApi(`/api/cuentas/${path}/`, {
    method: datos === undefined ? 'GET' : 'POST',
    datos,
  });
}
