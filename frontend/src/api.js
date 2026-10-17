let csrfToken;

export async function api(path, datos) {
  const response = await fetch(`/api/cuentas/${path}/`, {
    method: datos === undefined ? 'GET' : 'POST',
    credentials: 'same-origin',
    headers: datos === undefined ? {} : {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken || '',
    },
    ...(datos === undefined ? {} : { body: JSON.stringify(datos) }),
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error('El servidor no respondió correctamente. Comprueba que Django esté iniciado.');
  }
  if (result.csrfToken) csrfToken = result.csrfToken;
  if (!response.ok) {
    const messages = Object.values(result.errores || {}).flat();
    throw new Error(result.mensaje || messages.join(' ') || 'No se pudo completar la solicitud.');
  }
  return result;
}
