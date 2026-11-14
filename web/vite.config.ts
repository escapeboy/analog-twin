import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';

const cesium = 'node_modules/cesium/Build/Cesium';
const target = process.env.API_TARGET ?? 'http://100.85.138.47:8742';

export default defineConfig({
  base: './',
  define: { CESIUM_BASE_URL: JSON.stringify('./cesium') },
  plugins: [
    viteStaticCopy({
      targets: ['Assets', 'Widgets', 'Workers', 'ThirdParty'].map((d) => ({
        src: `${cesium}/${d}/**/*`,
        dest: `cesium/${d}`,
        rename: { stripBase: 5 },
      })),
    }),
  ],
  build: { chunkSizeWarningLimit: 6000 },
  server: { proxy: { '/api': target, '/tiles': target } },
  preview: { proxy: { '/api': target, '/tiles': target } },
});
