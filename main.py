from machine import sleep, SoftI2C, Pin
from utime import ticks_diff, ticks_ms
from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM

class HeartRateMonitor:
    """Filtra la señal PPG mediante media móvil y detecta picos de latidos."""

    def __init__(self, sample_rate=100, window_size=10, smoothing_window=5):
        self.sample_rate = sample_rate
        self.window_size = window_size
        self.smoothing_window = smoothing_window
        self.samples = []
        self.timestamps = []
        self.filtered_samples = []

    def add_sample(self, sample):
        """Ingresa una muestra bruta, registra su tiempo y calcula la media móvil."""
        timestamp = ticks_ms()
        self.samples.append(sample)
        self.timestamps.append(timestamp)

        # Suavizado de señal.
        if len(self.samples) >= self.smoothing_window:
            smoothed_sample = sum(self.samples[-self.smoothing_window :]) / self.smoothing_window
            self.filtered_samples.append(smoothed_sample)
        else:
            self.filtered_samples.append(sample)

        # Control de desbordamiento de memoria del búfer.
        if len(self.samples) > self.window_size:
            self.samples.pop(0)
            self.timestamps.pop(0)
            self.filtered_samples.pop(0)

    def find_peaks(self):
        """Identifica máximos locales en la señal filtrada usando un umbral dinámico."""
        peaks = []
        if len(self.filtered_samples) < 3: 
            return peaks

        # Umbral de detección al 50% de la amplitud de la ventana reciente.
        recent_samples = self.filtered_samples[-self.window_size :]
        min_val = min(recent_samples)
        max_val = max(recent_samples)
        threshold = min_val + (max_val - min_val) * 0.5 

        # Detección de picos.
        for i in range(1, len(self.filtered_samples) - 1):
            if (
                self.filtered_samples[i] > threshold
                and self.filtered_samples[i - 1] < self.filtered_samples[i]
                and self.filtered_samples[i] > self.filtered_samples[i + 1]
            ):
                peak_time = self.timestamps[i]
                peaks.append((peak_time, self.filtered_samples[i]))

        return peaks

    def calculate_heart_rate(self):
        """Convierte los intervalos de tiempo entre picos a BPM."""
        peaks = self.find_peaks()

        if len(peaks) < 2:
            return None

        # Promedio de intervalos entre picos (ms).
        intervals = []
        for i in range(1, len(peaks)):
            interval = ticks_diff(peaks[i][0], peaks[i - 1][0])
            intervals.append(interval)

        average_interval = sum(intervals) / len(intervals)

        # Conversión de ms a BPM.
        heart_rate = 60000 / average_interval 
        return heart_rate


def main():
    # --- Configuración de Hardware ---
    i2c = SoftI2C(
        sda=Pin(21),  # Línea de datos I2C.
        scl=Pin(22),  # Línea de reloj I2C.
        freq=400000,  # Frecuencia del bus a 400kHz.
    )

    sensor = MAX30102(i2c=i2c)

    # Validación de conexión I2C y compatibilidad del módulo.
    if sensor.i2c_address not in i2c.scan():
        print("Sensor no encontrado en el bus I2C.")
        return
    elif not (sensor.check_part_id()):
        print("ID de dispositivo incompatible.")
        return

    # Inicialización del sensor.
    sensor.setup_sensor()

    # Parámetros de adquisición de señal.
    sensor_sample_rate = 400
    sensor.set_sample_rate(sensor_sample_rate)
    sensor_fifo_average = 8
    sensor.set_fifo_average(sensor_fifo_average)
    sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)

    # Frecuencia real de salida (50 Hz).
    actual_acquisition_rate = int(sensor_sample_rate / sensor_fifo_average)

    # Instancia del algoritmo de procesamiento.
    hr_monitor = HeartRateMonitor(
        sample_rate=actual_acquisition_rate,
        window_size=int(actual_acquisition_rate * 3), 
    )

    # Variables de control temporal.
    hr_compute_interval = 2  
    ref_time = ticks_ms()

    # --- Bucle de Captura y Procesamiento ---
    while True:
        sensor.check()

        if sensor.available():
            # Extracción de datos brutos del FIFO.
            red_reading = sensor.pop_red_from_storage()
            ir_reading = sensor.pop_ir_from_storage()

            # Entrada de datos IR al algoritmo.
            hr_monitor.add_sample(ir_reading)

        # Cálculo y salida periódica de resultados.
        if ticks_diff(ticks_ms(), ref_time) / 1000 > hr_compute_interval:
            heart_rate = hr_monitor.calculate_heart_rate()
            
            if heart_rate is not None:
                print("❤️ Ritmo Cardíaco: {:.0f} BPM".format(heart_rate))
            else:
                print("⏳ Recalculando...")
            
            ref_time = ticks_ms()

if __name__ == "__main__":
    main()