import { solicitudApi } from '../api.js';
import { api } from '../cuentas/api.js';

const URL_TALLERES = '/api/gestion/talleres/';

export function listarTalleres() {
  return solicitudApi(URL_TALLERES);
}

export function crearTaller(datos) {
  return solicitudApi(URL_TALLERES, { method: 'POST', datos });
}

export function actualizarTaller(codigo, datos) {
  return solicitudApi(`${URL_TALLERES}${encodeURIComponent(codigo)}/`, {
    method: 'PATCH',
    datos,
  });
}

export function refrescarSesion() {
  return api('sesion');
}


export function consultarEspera(codigo) {
  return solicitudApi(`${URL_TALLERES}${encodeURIComponent(codigo)}/espera/`);
}
