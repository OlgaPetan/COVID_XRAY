import pandas as pd
import pydicom
import numpy as np
import os
import cv2
from pathlib import Path

print(pd.__version__)

labels = pd.read_csv('KCH_CXR_labels.csv')
labels = labels.sort_values('AccessionID')
print(labels.shape)

labels = labels.drop_duplicates(subset=['AccessionID'], ignore_index=True)
print(labels.shape)

PATH = '/nfs/project/covid/CXR/KCH_CXR'
save_path = '/nfs/project/richard/COVID/KCH_CXR_JPG'

Filename = []
AccessionID = []
Examination_Title = []
Age = []
Gender = []
SymptomOnset_DTM = []
Death_DTM = []
Died = []

for i, name in enumerate(labels.AccessionID):
    print(i, name)
    img_dir = os.path.join(PATH, name)
    files = [f for f in Path(img_dir).rglob('*.dcm')]
    #print(files)
    #if i > 100:
    #    break

    for f in files:
        #print(os.fspath(f.absolute()))
        ds = pydicom.dcmread(f)
        #print(ds)

        if "AcquisitionDateTime" in ds:
            datetime = ds.AcquisitionDateTime.split('.')[0]
        elif "ContributionDateTime" in ds:
            datetime = ds.ContributionDateTime.split('.')[0]
        year = datetime[:4]
        month = datetime[4:6]
        day = datetime[6:8]
        time = datetime[8::]
        #print(year, month, day, time)
        fname = name + '_' + datetime

        acc = labels.AccessionID[i]
        ext = labels.Examination_Title[i]
        age = labels.Age[i]
        gen = labels.Gender[i]
        sym = labels.SymptomOnset_DTM[i]
        dtm = labels.Death_DTM[i]
        ddd = labels.Died[i]

        try:
            img = ds.pixel_array.astype(np.float32)
            img -= img.min()
            img /= img.max()
            img = np.uint8(255.0*img)
            print(img.shape)

            save_name = os.path.join(save_path, (fname + '.jpg'))
            print(save_name)
            cv2.imwrite(save_name, img)

            Filename.append(fname)
            AccessionID.append(acc)
            Examination_Title.append(ext)
            Age.append(age)
            Gender.append(gen)
            SymptomOnset_DTM.append(sym)
            Death_DTM.append(dtm)
            Died.append(ddd)
            print(len(Filename), len(AccessionID), len(Died))

        except:
            print('Cannot load image')

print(len(Filename), len(AccessionID), len(Died))

df = pd.DataFrame({'Filename':Filename,
                   'AccessionID':AccessionID,
                   'Examination_Title':Examination_Title,
                   'Age':Age,
                   'Gender':Gender,
                   'SymptomOnset_DTM':SymptomOnset_DTM,
                   'Death_DTM':Death_DTM,
                   'Died':Died
                    })
df.to_csv('KCH_CXR_JPG.csv')
exit(0)







#csv = [f for f in Path(r'./').rglob('*.png')]
#csv = [f for f in Path(r'./').rglob('*.jpg')]
#csv = [f for f in Path(r'./').rglob('*.dcm')]
#files = []
#for f in csv:
#    files.append(os.fspath(f.absolute()))
#df = pd.DataFrame({'filepath':files})
#df.to_csv('out.csv')

filepaths = 'KCH_CXR.csv'
#filepaths = 'PUBLIC.csv'
df = pd.read_csv(filepaths)
print(df.shape)
print(df.head())

save_path = '/nfs/project/richard/COVID/KCH_CXR_JPG'
filelist = []
for f in df.filepath:
    #print(f)
    head, tail = os.path.split(f)
    tail = os.path.splitext(tail)[0]
    #print(tail)
    ds = pydicom.dcmread(f)
    try:
        img = ds.pixel_array.astype(np.float32)
        img -= img.min()
        img /= img.max()
        img = np.uint8(255.0*img)
        save_name = os.path.join(save_path, tail+'.jpg')
        cv2.imwrite(save_name, img)
        filelist.append(save_name)
    except:
        print('Cannot load image')

df = pd.DataFrame({'filepath':filelist})
df.to_csv('KCH_CXR_JPG.csv')
