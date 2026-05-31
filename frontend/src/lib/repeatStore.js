// Передача параметров «повторить прогон» из истории на страницу поиска.
// Простой модульный синглтон: история кладёт params, страница поиска забирает их
// один раз при монтировании.
let pending = null;

export const setRepeat = (params) => { pending = params; };
export const takeRepeat = () => { const p = pending; pending = null; return p; };
