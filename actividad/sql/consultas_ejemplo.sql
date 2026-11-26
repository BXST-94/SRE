-- Consultas de ejemplo (SQLite) sobre la muestra de reseñas.

-- 1) Reseñas por usuario (top 10 mas activos)
SELECT user_id, COUNT(*) AS interacciones
FROM reviews
GROUP BY user_id
ORDER BY interacciones DESC
LIMIT 10;

-- 2) Items mas reseñados (top 10)
SELECT parent_asin, COUNT(*) AS interacciones
FROM reviews
GROUP BY parent_asin
ORDER BY interacciones DESC
LIMIT 10;

-- 3) Distribucion de ratings
SELECT rating, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM reviews), 2) AS pct
FROM reviews
GROUP BY rating
ORDER BY rating;

-- 4) Actividad por mes (timestamp en ms)
SELECT strftime('%Y-%m', timestamp / 1000, 'unixepoch') AS mes, COUNT(*) AS n
FROM reviews
GROUP BY mes
ORDER BY mes;

-- 5) Usuarios con menos de 5 reseñas (la muestra conserva el historial completo de cada usuario)
SELECT user_id, COUNT(*) AS n
FROM reviews
GROUP BY user_id
HAVING COUNT(*) < 5
LIMIT 5;
