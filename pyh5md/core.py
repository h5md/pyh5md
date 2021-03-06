# Copyright 2012-2013 Pierre de Buyl
#
# This file is part of pyh5md
#
# pyh5md is free software and is licensed under the modified BSD license (see
# LICENSE file).

import numpy as np
import h5py
import time

TRAJECTORY_NAMES = ['position', 'velocity', 'force', 'species']
H5MD_SET = frozenset(['step', 'time', 'value'])

def populate_H5MD_data(g, name, shape, dtype):
    """Creates a step,time,value H5MD data group."""
    g.s = g.create_dataset('step', shape=(0,), dtype=np.int32, maxshape=(None,))
    g.t = g.create_dataset('time', shape=(0,), dtype=np.float64, maxshape=(None,))
    g.v = g.create_dataset('value', shape=(0,)+shape, dtype=dtype, maxshape=(None,)+shape)

def is_h5md(g):
    """Check whether a group is a well-defined H5MD time-dependent group. Raises
    an exception if a group contains the elements of H5MD_SET but does not
    comply to an equal length for all of them."""
    if H5MD_SET <= set(g.keys()):
        s_d = len(g['step'].shape)
        s_l = g['step'].shape[0]
        t_d = len(g['time'].shape)
        t_l = g['time'].shape[0]
        v_l = g['value'].shape[0]
        assert(
            (s_d == 1) and (t_d == 1) and (s_l == t_l) and (s_l == v_l)
            )
        return True
    else:
        return False

class Walker(object):
    """Finds all HDF5 groups within a given group."""
    def __init__(self, f):
        self.f = f
        self.walk_list = []

    def walk(self, g=None):
        if g==None:
            g = self.f['/']
        if type(g)==h5py.Group:
            if is_h5md(g): self.walk_list.append(g)
            for k in g.keys():
                self.walk(g[k])

    def get_list(self):
        return self.walk_list

    def check(self):
        if len(self.walk_list)==0:
            raise Exception('Nothing to check')
        for g in self.walk_list:
            assert(is_h5md(g))

class TimeData(h5py.Group):
    """Represents time-dependent data within a H5MD file."""
    def __init__(self, parent, name, shape=None, dtype=None, data=None):
        """Create a new TimeData object."""
        if name in parent.keys():
            self._id = h5py.h5g.open(parent.id, name)
            self.step = self['step']
            self.time = self['time']
            self.value = self['value']
        else:
            if data is not None:
                if shape is not None or isinstance(dtype, np.dtype):
                    raise Exception('Overspecification')
                else:
                    self._id = h5py.h5g.create(parent.id, name)
                    populate_H5MD_data(self, name, data.shape, data.dtype)
            else:
                self._id = h5py.h5g.create(parent.id, name)
                populate_H5MD_data(self, name, shape, dtype)

    def append(self, data, step, time):
        """Appends a time slice to the data group."""
        s = self['step']
        t = self['time']
        v = self['value']
        if not isinstance(data, np.ndarray):
            data = np.array(data, ndmin=1)
        assert s.shape[0]==t.shape[0] and t.shape[0]==v.shape[0]
        if data.shape==v.shape[1:] and data.dtype==v.dtype:
            idx = v.shape[0]
            v.resize(idx+1,axis=0)
            v[-1] = data
            s.resize(idx+1, axis=0)
            s[-1] = step
            t.resize(idx+1, axis=0)
            t[-1] = time

class FixedData(h5py.Dataset):
    """Represents time-independent data within a H5MD file."""
    def __init__(self, parent, name, shape=None, dtype=None, data=None):
        if name not in parent.keys():
            parent.create_dataset(name, shape, dtype)
        self._id = h5py.h5d.open(parent.id, name)

def particle_data(group, name=None, shape=None, dtype=None, data=None, time=True):
    """Returns particles data as a FixedData or TimeData."""
    if name is None:
        raise Exception('No name provided')
    if name in group.keys():
        item = group[name]
        if type(item)==h5py.Group:
            assert is_h5md(item)
            return TimeData(group, name)
        elif type(item)==h5py.Dataset:
            assert shape==dtype==data==None
            return FixedData(group, name)
        else:
            raise Exception('name does not provide H5MD data')
    else:
        if time:
            return TimeData(group, name, shape, dtype, data)
        else:
            return FixedData(group, name, shape, dtype, data)

class ParticlesGroup(h5py.Group):
    """Represents a particles group within a H5MD file."""
    def __init__(self, parent, name):
        """Create a new ParticlesGroup object."""
        if 'particles' not in parent.keys():
            parent.create_group('particles')
        p = parent['particles']
        if name in p.keys():
            self._id = h5py.h5g.open(p.id, name)
        else:
            self._id = h5py.h5g.create(p.id, name)
    def trajectory(self, name, shape=None, dtype=None, data=None, time=True):
        """Returns data as a TimeData or FixedData object."""
        return particle_data(self, name, shape, dtype, data, time=True)


class H5MD_File(object):
    """Class to create and read H5MD compliant files."""
    def __init__(self,filename,mode,**kwargs):
        """Create or read an H5MD file, according to argument mode.
        mode should be 'r', 'r+' or 'w'"""
        if mode not in ['r','r+','w']:
            print 'Unknown mode in H5MDFile'
            return
        if mode=='w':
            kw = kwargs.keys()
            for key in ['creator', 'author', 'creator_version']:
                if key not in kw:
                    print 'missing arguments in H5MDFile'
                    return
        self.f = h5py.File(filename, mode)
        if mode=='w':
            self.f.create_group('h5md')
            for key in ['creator', 'author', 'creator_version']:
                self.f['h5md'].attrs[key] = kwargs[key]
            self.f['h5md'].attrs['version'] = np.array([1,0])
            self.f['h5md'].attrs['creation_time'] = int(time.time())

    def close(self):
        """Closes the HDF5 file."""
        self.f.close()

    def particles_group(self, group_name):
        """Adds or open a group in /particles. If /particles does not exist,
        it will be created."""
        return ParticlesGroup(self.f, group_name)

    def observable(self, obs_name,*args,**kwargs):
        """Returns observable data as a TimeData object."""
        if 'observables' not in self.f.keys():
            self.f.create_group('observables')
        return TimeData(self.f['observables'],obs_name,*args,**kwargs)
        
    def check(self):
        """Checks the file conformance."""
        # Checks the presence of the global attributes.
        attrs = set(['author', 'creator', 'creator_version', 'creation_time', 'version'])
        assert(attrs <= set(self.f['h5md'].attrs.keys()))
        # Check that version is of appropriate shape.
        assert(self.f['h5md'].attrs['version'].shape==(2,))
        w = Walker(self.f)
        w.walk()
