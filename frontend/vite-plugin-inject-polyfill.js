export default function injectPolyfillPlugin() {
  return {
    name: "inject-promise-finally-polyfill",
    transformIndexHtml: {
      order: "pre",
      handler(html) {
        const polyfillScript = `
    <script>
      (function() {
        if (typeof Promise !== 'undefined' && !Promise.prototype.finally) {
          Promise.prototype.finally = function(onFinally) {
            var constructor = this.constructor || Promise;
            return this.then(
              function(value) {
                return constructor.resolve(onFinally && onFinally()).then(function() {
                  return value;
                });
              },
              function(reason) {
                return constructor.resolve(onFinally && onFinally()).then(function() {
                  throw reason;
                });
              }
            );
          };
        }
      })();
    </script>`;

        // Инъектировать сразу после <head>
        return html.replace(/<head>/, "<head>" + polyfillScript);
      },
    },
  };
}
