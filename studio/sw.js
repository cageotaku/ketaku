/* 스튜디오 매물 서비스 워커
   - 앱 화면: 인터넷이 되면 늘 새로 받아 최신 앱을 열고 보관해 둔다. 끊겼거나 3초 안에 안 오면 보관해 둔 화면을 연다.
   - 사진(data/p/*.bin): 사진마다 파일 이름이 달라서 한 번 받은 것은 기기에 두고 다시 받지 않는다. 내려간 사진은 앱이 지운다.
   - 글꼴: 한 번 받은 것은 기기에 둔다.
   - 매물 데이터(data/board.bin)는 건드리지 않는다. 앱이 늘 새로 받고, 안 되면 저장해 둔 매물을 보여 준다.
   - 보관함 이름(SHELL)을 바꾸면 기기마다 앱 화면을 새로 받아 보관한다(v2, 2026-11-22: 방 탭 전 화면이 남은 기기).
     앱 화면(index.html)은 app-version 값으로 새 버전을 알아보고 같은 보관함에 새 화면을 넣은 뒤 다시 연다.
   문제가 생기면 이 파일 내용을 아래 두 줄로 바꿔 올리면 다음에 앱을 열 때 꺼진다.
     self.addEventListener('install', function () { self.skipWaiting(); });
     self.addEventListener('activate', function () { self.registration.unregister(); });
*/
'use strict';
var SHELL = 'studio-shell-v2', PHOTOS = 'studio-photos-v1', FONTS = 'studio-fonts-v1';
var BASE = new URL('./', self.location.href).pathname;
var WAIT_MS = 3000;

function later(e, p) {
  try { e.waitUntil(p.catch(function () {})); } catch (x) {}
}

self.addEventListener('install', function (e) {
  e.waitUntil(fetch(BASE, { cache: 'no-cache' }).then(function (res) {
    if (!res.ok) throw new Error('http ' + res.status);
    // 다른 주소를 거쳐 온 화면은 아이폰이 앱 화면으로 쓰지 못해 새로 감싸 보관한다
    if (!res.redirected) return res;
    return res.blob().then(function (b) { return new Response(b, { status: res.status, statusText: res.statusText, headers: res.headers }); });
  }).then(function (res) {
    return caches.open(SHELL).then(function (c) { return c.put(BASE, res); });
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (names) {
    return Promise.all(names.filter(function (n) {
      return n.indexOf('studio-') === 0 && [SHELL, PHOTOS, FONTS].indexOf(n) < 0;
    }).map(function (n) { return caches.delete(n); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin === self.location.origin) {
    if (req.mode === 'navigate') {
      if (url.pathname === BASE || url.pathname === BASE + 'index.html') e.respondWith(page(e));
    } else if (url.pathname.indexOf(BASE + 'data/p/') === 0 && /\/[0-9a-f]{32}\.bin$/.test(url.pathname)) {
      e.respondWith(keep(e, PHOTOS));
    }
    return;
  }
  if (url.hostname === 'fonts.gstatic.com') e.respondWith(keep(e, FONTS));
  else if (url.hostname === 'fonts.googleapis.com') e.respondWith(fresh(e, FONTS));
});

/* 앱 화면: 새로 받아 보여 주고 보관한다. 인터넷이 끊겼거나 3초 안에 안 오면 보관해 둔 화면을 연다 */
function page(e) {
  var saving = Promise.resolve();
  var net = fetch(e.request).then(function (res) {
    if (res.status >= 500) throw new Error('http ' + res.status);
    if (res.ok && res.type === 'basic') {
      var copy = res.clone();
      saving = caches.open(SHELL).then(function (c) { return c.put(BASE, copy); });
    }
    return res;
  });
  later(e, net.then(function () { return saving; }));
  var stored = function () { return caches.match(BASE, { cacheName: SHELL }); };
  var safe = net.catch(function () {
    return stored().then(function (hit) { if (hit) return hit; throw new Error('offline'); });
  });
  var slow = new Promise(function (resolve) { setTimeout(resolve, WAIT_MS); })
    .then(stored).then(function (hit) { return hit || safe; });
  return Promise.race([safe, slow]);
}

/* 보관함에 있으면 그것을 쓰고, 없으면 받아서 보관한다 (사진, 글꼴 파일) */
function keep(e, name) {
  var req = e.request;
  return caches.open(name).then(function (c) {
    return c.match(req, { ignoreVary: true }).then(function (hit) {
      if (hit) return hit;
      return fetch(req).then(function (res) {
        if (res.ok) later(e, c.put(req, res.clone()));
        return res;
      });
    });
  });
}

/* 보관해 둔 것을 바로 쓰고, 뒤에서 새로 받아 바꿔 둔다 (글꼴 목록) */
function fresh(e, name) {
  var req = e.request;
  return caches.open(name).then(function (c) {
    return c.match(req, { ignoreVary: true }).then(function (hit) {
      var net = fetch(req).then(function (res) {
        if (!res.ok) return res;
        return c.put(req, res.clone()).then(function () { return res; }, function () { return res; });
      });
      if (!hit) return net;
      later(e, net);
      return hit;
    });
  });
}
