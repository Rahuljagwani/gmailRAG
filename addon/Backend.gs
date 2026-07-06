/**
 * Backend client for Grove: calls the FastAPI /answer endpoint.
 *
 * The backend URL and shared secret are read from Script Properties (Project Settings ->
 * Script Properties), NOT hard-coded, so the secret never lives in source. Set:
 *   BACKEND_URL    = https://email-rag-backend-ihyc.onrender.com
 *   SHARED_SECRET  = <the same value as backend BACKEND_SHARED_SECRET>
 */

/** Reads backend config from Script Properties; throws a friendly error if unset. */
function getBackendConfig_() {
  var props = PropertiesService.getScriptProperties();
  var url = (props.getProperty('BACKEND_URL') || '').replace(/\/+$/, '');
  var secret = props.getProperty('SHARED_SECRET') || '';
  if (!url || !secret) {
    throw new Error(
      'Grove is not configured. Set BACKEND_URL and SHARED_SECRET in ' +
        'Project Settings -> Script Properties.'
    );
  }
  return { url: url, secret: secret };
}

/**
 * POST the open email to /answer and return the structured result.
 * @param {string} subject
 * @param {string} body
 * @return {{answer: string, citations: Object[], has_clear_answer: boolean, retrieval: Object[]}}
 */
function callAnswerBackend_(subject, body) {
  var cfg = getBackendConfig_();
  var response = UrlFetchApp.fetch(cfg.url + '/answer', {
    method: 'post',
    contentType: 'application/json',
    headers: { 'X-API-Key': cfg.secret },
    payload: JSON.stringify({ subject: subject, body: body }),
    muteHttpExceptions: true
  });

  var code = response.getResponseCode();
  var text = response.getContentText();
  if (code !== 200) {
    var detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch (err) {
      // leave detail as raw text
    }
    throw new Error('Backend error (HTTP ' + code + '): ' + detail);
  }
  return JSON.parse(text);
}
