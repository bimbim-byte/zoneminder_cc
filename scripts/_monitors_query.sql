-- Kueri sementara: data mentah Monitor untuk verifikasi perilaku ZM 1.38.
-- Perhatikan: hanya kolom yang ADA di skema 1.38 (AnalisisFPS = AnalysisFPSLimit).
SELECT Id, Name, Type, Function, Method,
       COALESCE(Options, '')      AS Options,
       COALESCE(MaxFPS, 0)        AS MaxFPS,
       COALESCE(AlarmMaxFPS, 0)   AS AlarmMaxFPS,
       COALESCE(AnalysisFPSLimit, 0) AS AnalysisFPSLimit,
       COALESCE(FrameSkip, 0)     AS FrameSkip,
       COALESCE(MotionFrameSkip, 0) AS MotionFrameSkip,
       Path
  FROM Monitors
 ORDER BY Id;
