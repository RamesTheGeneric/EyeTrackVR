import numpy as np
import time
import os
import cv2
from enums import EyeLR
#higher intensity means more closed/ more white/less pupil

#Hm I need an acronym for this, any ideas?
#IBO Intensity Based Openess

# HOW THIS WORKS: 
# we get the intensity of pupil area from HSF crop, When the eyelid starts to close, the pupil starts being obstructed by skin which is generally lighter than the pupil. 
# This causes the intensity to increase. We save all of the darkest intensities of each pupil position to calculate for pupil movement. 
# ex. when you look up there is less pupil visible, which results in an uncalculated change in intensity even though the eyelid has not moved in a meaningful way. 
# We compare the darkest intensity of that area, to the lightest (global) intensity to find the appropriate openness state via a float.


# Note.
# OpenCV on Windows will generate an error if the file path contains non-ASCII characters when using cv2.imread(), cv2.imwrite(), etc.
# https://stackoverflow.com/questions/43185605/how-do-i-read-an-image-from-a-path-with-unicode-characters
# https://github.com/opencv/opencv/issues/18305

def csv2data(frameshape, filepath):
    # For data checking
    frameshape = (frameshape[0], frameshape[1]+1)
    out = np.zeros(frameshape, dtype=np.uint32)
    xy_list = []
    val_list = []
    with open(filepath, mode="r", encoding="utf-8") as in_f:
        # Skip header.
        _ = in_f.readline()
        for s in in_f:
            xyval = [int(val) for val in s.strip().split(',')]
            xy_list.append((xyval[0], xyval[1]))
            val_list.append(xyval[2])
    xy_list = np.array(xy_list)
    val_list = np.array(val_list)
    out[xy_list[:, 1], xy_list[:, 0]] = val_list[:]
    return out


def data2csv(data_u32, filepath):
    # For data checking
    nonzero_index = np.nonzero(data_u32) #(row,col)
    data_list = data_u32[nonzero_index].tolist()
    datalines = ["{},{},{}\n".format(x, y, val) for y, x, val in zip(*nonzero_index, data_list)]
    with open(filepath, 'w', encoding="utf-8") as out_f:
        out_f.write("x,y,intensity\n")
        out_f.writelines(datalines)
    return


def u32_1ch_to_u16_3ch(img):
    out = np.zeros((*img.shape[:2], 3), dtype=np.uint16)
    # https://github.com/numpy/numpy/issues/2524
    # https://stackoverflow.com/questions/52782511/why-is-numpy-slower-than-python-for-left-bit-shifts
    out[:, :, 0] = img & np.uint32(65535)
    out[:, :, 1] = (img >> np.uint32(16)) & np.uint32(65535)
    
    return out


def u16_3ch_to_u32_1ch(img):
    # The image format with the most bits that can be displayed on Windows without additional software and that opencv can handle is PNG's uint16
    out = img[:, :, 0].astype(np.float64)  # float64 = max 2^53
    cv2.add(out, img[:, :, 1].astype(np.float64)*np.float64(65536), dst=out)  # opencv did not have uint32 type
    return out.astype(np.uint32)  # cast


def newdata(frameshape):
    print("Initialise data for blinking.")
    return np.zeros(frameshape, dtype=np.uint32)


class IntensityBasedOpeness:
    def __init__(self, eyeside: EyeLR):
        # todo: It is necessary to consider whether the filename can be changed in the configuration file, etc.
        self.imgfile = "IBO_LEFT.png" if eyeside is EyeLR.LEFT else "IBO_RIGHT.png"
        # self.data[0, -1] = maxval, [1, -1] = rotation, [2, -1] = x, [3, -1] = y
        self.data = None
        self.lct = None
        self.maxval = 0
        # self.img_roi = self.now_roi == {"rotation": 0, "x": 0, "y": 0}
        self.img_roi = np.zeros(3, dtype=np.int32)
        self.now_roi = np.zeros(3, dtype=np.int32)
        
    def check(self, frameshape):
        # 0 in data is used as the initial value.
        # When assigning a value, +1 is added to the value to be assigned.
        self.load(frameshape)
        # self.maxval = self.data[0, -1]
        if self.lct is None:
            self.lct = time.time()
    
    def load(self, frameshape):
        req_newdata = False
        # Not very clever, but increase the width by 1px to save the maximum value.
        frameshape = (frameshape[0], frameshape[1] + 1)
        if self.data is None:
            print("Load data for blinking: {}".format(self.imgfile))
            if os.path.isfile(self.imgfile):
                try:
                    img = cv2.imread(self.imgfile, flags=cv2.IMREAD_UNCHANGED)
                    # check code: cv2.absdiff(img,u32_1ch_to_u16_3ch(u16_3ch_to_u32_1ch(img)))
                    if img.shape[:2] != frameshape:
                        print("size does not match the input frame.")
                        req_newdata = True
                    else:
                        self.data = u16_3ch_to_u32_1ch(img)
                        self.img_roi[:] = self.data[1:4, -1]
                        if not np.array_equal(self.img_roi, self.now_roi):
                            # If the ROI recorded in the image file differs from the current ROI
                            req_newdata = True
                        else:
                            self.maxval = self.data[0, -1]
                except:
                    print("File read error: {}".format(self.imgfile))
                    req_newdata = True
            else:
                print("File does not exist.")
                req_newdata = True
        else:
            if self.data.shape != frameshape or not np.array_equal(self.img_roi, self.now_roi):
                # If the ROI recorded in the image file differs from the current ROI
                #todo: Using the previous and current frame sizes and centre positions from the original, etc., the data can be ported to some extent, but there may be many areas where code changes are required.
                print("Frame size changed.")
                req_newdata = True
        if req_newdata:
            self.data = newdata(frameshape)
            self.maxval = 0
            self.img_roi = self.now_roi.copy()
        # data2csv(self.data, "a.csv")
        # csv2data(frameshape,"a.csv")
        
    def save(self):
        self.data[0, -1] = self.maxval
        self.data[1:4, -1] = self.now_roi
        cv2.imwrite(self.imgfile, u32_1ch_to_u16_3ch(self.data))
        print("SAVED: {}".format(self.imgfile))
        
    def change_roi(self, roiinfo: dict):
        self.now_roi[:] = [v for v in roiinfo.values()]
    
    def intense(self, x, y, frame):
        self.check(frame.shape)
        int_x, int_y = int(x), int(y)
    
        # upper_x = min(int_x + 25, frame.shape[1]) #TODO make this a setting
        # lower_x = max(int_x - 25, 0)
        # upper_y = min(int_y + 25, frame.shape[0])
        # lower_y = max(int_y - 25, 0)

        # frame_crop = frame[lower_y:upper_y, lower_x:upper_x]
        frame_crop = frame
    
        # The same can be done with cv2.integral, but since there is only one area of the rectangle for which we want to know the total value, there is no advantage in terms of computational complexity.
        intensity = frame_crop.sum() + 1
        # numpy:np.sum(),ndarray.sum()
        # opencv:cv2.sumElems()
        # I don't know which is faster.
        # print(frame.shape[1], frame.shape[0], int_x, int_y, eye)
        changed = False
        newval_flg = False
        oob = False
        if int_x >= frame.shape[1]:
            int_x = frame.shape[1] - 1
            obb = True
            print('CAUGHT X OUT OF BOUNDS')
    
        if int_x < 0:
            int_x = True
            print('CAUGHT X UNDER BOUNDS')

        if int_y >= frame.shape[0]:
            int_y = frame.shape[0] - 1
            oob = True
            print('CAUGHT Y OUT OF BOUNDS')

        if int_y < 0:
            int_y = 1
            oob = True
            print('CAUGHT Y UNDER BOUNDS')

        if oob != True:
            data_val = self.data[int_y, int_x]
        else:
            data_val = 0
        # max pupil per cord
        if data_val == 0:
            # The value of the specified coordinates has not yet been recorded.
            self.data[int_y, int_x] = intensity
            changed = True
            newval_flg = True
        else:
            if intensity < data_val:  # if current intensity value is less (more pupil), save that
                self.data[int_y, int_x] = intensity  # set value
                changed = True
               # print("var adjusted")
            else:
                intensitya = max(data_val - 3, 1)  # if current intensity value is less (more pupil), save that
                self.data[int_y, int_x] = intensitya  # set value
                changed = True
            
        # min pupil global
        if self.maxval == 0:  # that value is not yet saved
            self.maxval = intensity  # set value at 0 index
          #  print("create max", intensity)
        else:
            if intensity > self.maxval:  # if current intensity value is more (less pupil), save that NOTE: we have the
                self.maxval = intensity  # set value at 0 index
              #  print("new max", intensity)
            else:
                intensityd = max(self.maxval - 10, 1)  # continuously adjust closed intensity, will be set when user blink, used to allow eyes to close when lighting changes
                self.maxval = intensityd  # set value at 0 index
    
        if newval_flg:
            # Do the same thing as in the original version.
            print('[INFO] Something went wrong, assuming blink.')
            eyeopen = 0.7
        else:
            maxp = self.data[int_y, int_x]
            minp = self.maxval
            diffp = minp - maxp if (minp - maxp) != 0 else 1
            eyeopen = (intensity - maxp) / diffp
            eyeopen = 1 - eyeopen
            # eyeopen = eyeopen - 0.2
            # print(intensity, maxp, minp, x, y)
            print(f"EYEOPEN: {eyeopen}")
            # print(int(x), int(y), eyeopen, maxp, minp)
        # print(self.data[0, -1])
        # print(self.maxval)
        if changed and ((time.time() - self.lct) > 4):  # save every 4 seconds if something changed to save disk usage
            self.save()
            self.lct = time.time()
        return eyeopen