import os
import onnxruntime
import numpy as np
import cv2
import time
import math
from queue import Queue
import threading
from one_euro_filter import OneEuroFilter
import psutil
from utils.misc_utils import resource_path
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "1"

frames = 0
models = Path("Models")


def run_model(input_queue, output_queue, session):
    while True:
        frame = input_queue.get()
        if frame is None:
            break

        img_np = np.array(frame, dtype=np.float32) / 255.0
        gray_img = 0.299 * img_np[:, :, 0] + 0.587 * img_np[:, :, 1] + 0.114 * img_np[:, :, 2]

        gray_img = np.expand_dims(np.expand_dims(gray_img, axis=0), axis=0)

        ort_inputs = {session.get_inputs()[0].name: gray_img}
        pre_landmark = session.run(None, ort_inputs)
        pre_landmark = np.reshape(pre_landmark, (-1, 2))
        output_queue.put((frame, pre_landmark))


def run_onnx_model(queues, session, frame):
    for queue in queues:
        if not queue.full():
            queue.put(frame)
            break


class LEAP_C:
    def __init__(self):
        self.last_lid = None
        self.current_image_gray = None
        self.current_image_gray_clean = None
        onnxruntime.disable_telemetry_events()
        self.num_threads = 1
        self.queue_max_size = 1
        self.model_path = resource_path(models / "pfld-sim.onnx")

        self.print_fps = False
        self.frames = 0
        self.queues = [Queue(maxsize=self.queue_max_size) for _ in range(self.num_threads)]
        self.threads = []
        self.model_output = np.zeros((12, 2))
        self.output_queue = Queue(maxsize=self.queue_max_size)
        self.start_time = time.time()

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_mem_pattern = False

        self.one_euro_filter_float = OneEuroFilter(np.random.rand(1, 2), min_cutoff=0.0004, beta=0.9)
        self.dmax = 0
        self.dmin = 0
        self.openlist = []
        self.maxlist = []
        self.previous_time = None
        self.old_matrix = None
        self.total_velocity_new = 0
        self.total_velocity_avg = 0
        self.total_velocity_old = 0
        self.old_per = 0.0
        self.delta_per_neg = 0.0
        self.ort_session1 = onnxruntime.InferenceSession(self.model_path, opts, providers=["CPUExecutionProvider"])

        for i in range(self.num_threads):
            thread = threading.Thread(
                target=run_model,
                args=(self.queues[i], self.output_queue, self.ort_session1),
                name=f"Thread {i}",
            )
            self.threads.append(thread)
            thread.start()

    def leap_run(self):
        img = self.current_image_gray_clean.copy()
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        img_height, img_width = img.shape[:2]

        frame = cv2.resize(img, (112, 112))
        imgvis = self.current_image_gray.copy()
        run_onnx_model(self.queues, self.ort_session1, frame)

        if not self.output_queue.empty():
            frame, pre_landmark = self.output_queue.get()

            for point in pre_landmark:
                x, y = point
                x = int(x * img_width)
                y = int(y * img_height)
                cv2.circle(imgvis, (x, y), 3, (255, 255, 0), -1)
                cv2.circle(imgvis, (x, y), 1, (0, 0, 255), -1)

            d1 = math.dist(pre_landmark[1], pre_landmark[3])
            d2 = math.dist(pre_landmark[2], pre_landmark[4])
            d = (d1 + d2) / 2

         #   if len(self.openlist) > 0 and d >= np.percentile(self.openlist, 80) and len(self.openlist) < self.calibration_samples:
           #     self.maxlist.append(d)


            normal_open = np.percentile(self.openlist, 90) if len(self.openlist) >= 10 else 0.8

            if self.calib == 0:
                self.openlist = []

            if len(self.openlist) < self.calibration_samples:
                self.openlist.append(d)

            try:
                if len(self.openlist) > 0:
                    per = (d - normal_open) / (np.percentile(self.openlist, 2) - normal_open)
                    per = 1 - per
                    per = np.clip(per, 0.0, 1.0)
                else:
                    per = 0.8
            except:
                per = 0.8

            x = pre_landmark[6][0]
            y = pre_landmark[6][1]

            self.last_lid = per
            calib_array = np.array([per, per]).reshape(1, 2)
            per = self.one_euro_filter_float(calib_array)[0][0]

            if per <= 0.25:
                per = 0.0

            return imgvis, float(x), float(y), per

        imgvis = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        return imgvis, 0, 0, 0


class External_Run_LEAP:
    def __init__(self):
        self.algo = LEAP_C()

    def run(self, current_image_gray, current_image_gray_clean, calib, calibration_samples):
        self.algo.current_image_gray = current_image_gray
        self.algo.current_image_gray_clean = current_image_gray_clean
        self.algo.calib = calib
        self.algo.calibration_samples = calibration_samples
        img, x, y, per = self.algo.leap_run()
        return img, x, y, per
