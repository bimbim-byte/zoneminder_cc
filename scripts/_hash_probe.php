<?php
// REPRODUKSI: buktikan bahwa jalur lama dashboard/checker menghasilkan
// "Unable to authenticate user from auth hash" dan "Login denied".
//
// Jalankan: docker exec zoneminder php /tmp/hp.php

define('LOG', '/var/log/zm/web_php.log');

function counters() {
    $t = @file_get_contents(LOG);
    return array(
        'hash'   => substr_count($t, 'auth hash'),
        'denied' => substr_count($t, 'Login denied'),
        'ok'     => substr_count($t, 'Login successful'),
    );
}

function page($path, $cookies = '', $post = null) {
    $hdr = "Content-Type: application/x-www-form-urlencoded\r\n";
    if ($cookies) {
        $hdr .= 'Cookie: ' . trim($cookies) . "\r\n";
    }
    $ctx = stream_context_create(array('http' => array(
        'method'  => $post === null ? 'GET' : 'POST',
        'header'  => $hdr,
        'content' => $post === null ? '' : http_build_query($post),
        'ignore_errors' => true,
        'follow_location' => 0,
        'timeout' => 10,
    )));
    $body = @file_get_contents('http://localhost' . $path, false, $ctx);
    $code = 0;
    $newc = '';
    foreach (($http_response_header ?? array()) as $h) {
        if (preg_match('#^HTTP/\S+\s+(\d+)#', $h, $m)) {
            $code = (int)$m[1];
        }
        if (stripos($h, 'Set-Cookie:') === 0) {
            $newc .= ' ' . trim(explode(';', substr($h, 11))[0]);
        }
    }
    return array($code, (string)$body, $newc);
}

echo "=== A. JALUR LAMA: GET /zm/ tanpa kredensial (dipakai wait_for_zoneminder) ===\n";
$b = counters();
list($code, $body, $c) = page('/zm/');
$a = counters();
printf("  GET /zm/ -> http=%s  authhash+=%d denied+=%d\n",
    $code, $a['hash'] - $b['hash'], $a['denied'] - $b['denied']);

echo "\n=== B. JALUR LAMA: POST form login field polos dgn password benar ===\n";
$b = counters();
list($code, $body, $c) = page('/zm/index.php', $c, array(
    'username' => 'admin', 'password' => 'P@ssw0rd', 'action' => 'login',
));
$a = counters();
printf("  POST plain -> http=%s  authhash+=%d denied+=%d ok+=%d\n",
    $code, $a['hash'] - $b['hash'], $a['denied'] - $b['denied'], $a['ok'] - $b['ok']);

echo "\n=== C. JALUR BARU: GET /zm/api/host/getVersion.json (pengganti di checker) ===\n";
$b = counters();
list($code, $body, $c) = page('/zm/api/host/getVersion.json');
$a = counters();
printf("  GET getVersion -> http=%s  authhash+=%d denied+=%d\n",
    $code, $a['hash'] - $b['hash'], $a['denied'] - $b['denied']);

echo "\n=== D. JALUR BARU: login state-secret dgn password benar ===\n";
$secret = sha1('zm');
$b = counters();
list($code, $body, $c2) = page('/zm/index.php', $c, array(
    $secret . '__user[username]' => 'admin',
    $secret . '__user[password]' => 'P@ssw0rd',
    $secret . '__action' => 'login',
    '__csrf_magic' => 'csrfMagicToken:' . $secret,
));
$a = counters();
printf("  POST state-secret -> http=%s  authhash+=%d denied+=%d ok+=%d\n",
    $code, $a['hash'] - $b['hash'], $a['denied'] - $b['denied'], $a['ok'] - $b['ok']);

echo "\n=== 5 baris log terakhir ===\n";
foreach (array_slice(file(LOG), -5) as $l) {
    echo '  ', $l;
}
